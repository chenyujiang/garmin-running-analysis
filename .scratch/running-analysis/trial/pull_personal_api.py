"""Trial pull against the Garmin Connect Personal API (ticket 03).

Reads the API key from the repo-root .env without ever printing it.
Raw responses go to trial/data/ (gitignored). Stdout only shows shapes,
timings and errors, never the key or token.
"""

import json
import sys
import time
import zipfile
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

from garmin_personal_api import (
    GarminPersonalApiClient,
    GarminPersonalApiError,
    HttpError,
    PersonalApiAuthenticator,
)

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "data" / "personal_api"
PAUSE_S = 1.5
N_RUNS = 10


def load_key() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line and line.split("=", 1)[0].isidentifier():
            line = line.split("=", 1)[1]
        return line.strip().strip("'\"")
    sys.exit(".env has no key line")


KEY = load_key()
SECRETS: list[str] = [KEY]


def say(*parts) -> None:
    text = " ".join(str(p) for p in parts)
    for s in SECRETS:
        text = text.replace(s, "<redacted>")
    print(text, flush=True)


def save(name: str, data) -> None:
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def shape(data) -> str:
    if isinstance(data, list):
        return f"list[{len(data)}]" + (f" of {shape(data[0])}" if data else "")
    if isinstance(data, dict):
        return "dict{" + ", ".join(sorted(data.keys())) + "}"
    return type(data).__name__


def call(label: str, fn, *args, **kwargs):
    """Run one request, log timing and errors, pause afterwards."""
    t0 = time.perf_counter()
    try:
        result = fn(*args, **kwargs)
        ok = True
    except HttpError as err:
        result = None
        ok = False
        say(f"  ! {label}: HTTP {err.status_code} {err.method} {err.url}")
        say(f"    {str(err.response_text)[:300]}")
    except GarminPersonalApiError as err:
        result = None
        ok = False
        say(f"  ! {label}: {err}")
    dt = time.perf_counter() - t0
    if ok:
        size = len(result) if isinstance(result, bytes) else len(json.dumps(result))
        say(f"  {label}: {dt:.2f}s, {size} bytes")
    time.sleep(PAUSE_S)
    return result


def main() -> None:
    t0 = time.perf_counter()
    with PersonalApiAuthenticator() as auth:
        token = auth.obtain_token(KEY)
    SECRETS.append(token.access_token)
    say(f"token: {time.perf_counter() - t0:.2f}s, expires_at={token.expires_at}")

    today = date.today()
    with GarminPersonalApiClient(token.access_token) as client:
        say("== profile / zones")
        save("user_profile_settings.json", call("user_profile_settings", client.get_user_profile_settings))
        save("heart_rate_zones.json", call("heart_rate_zones", client.get_heart_rate_zones))

        say("== recent activities")
        acts = call("search_activities limit=50", client.search_activities, limit=50) or []
        save("activities_recent.json", acts)
        say("  shape:", shape(acts))
        if isinstance(acts, dict):
            say("  (dict response, inspect activities_recent.json)")
            acts = []
        types = {}
        for a in acts:
            t = a.get("activityType")
            key = t.get("typeKey") if isinstance(t, dict) else t
            types[key] = types.get(key, 0) + 1
        say("  activity types:", types)

        runs = [
            a for a in acts
            if "run" in json.dumps(a.get("activityType", "")).lower()
        ][:N_RUNS]
        say(f"== {len(runs)} runs: detail + download")
        for a in runs:
            aid = a.get("activityId")
            detail = call(f"get_activity {aid}", client.get_activity, aid)
            save(f"activities/{aid}.json", detail)
            blob = call(f"download_activity {aid}", client.download_activity, aid)
            if blob is None:
                continue
            save(f"activities/{aid}.download", blob)
            try:
                with zipfile.ZipFile(BytesIO(blob)) as z:
                    for info in z.infolist():
                        say(f"    zip: {info.filename} {info.file_size} bytes")
                        save(f"activities/{aid}/{info.filename}", z.read(info))
            except zipfile.BadZipFile:
                say(f"    not a zip, first bytes: {blob[:16]!r}")

        say("== health, last 7 days")
        start, end = today - timedelta(days=7), today - timedelta(days=1)
        for label, fn in [
            ("daily_hrv_summaries", client.get_daily_hrv_summaries),
            ("daily_sleep_summaries", client.get_daily_sleep_summaries),
            ("daily_summaries", client.get_daily_summaries),
        ]:
            data = call(label, fn, start, end)
            save(f"{label}.json", data)
            say("    shape:", shape(data))
        for label, fn in [
            ("daily_hrv", client.get_daily_hrv),
            ("daily_sleep", client.get_daily_sleep),
        ]:
            data = call(f"{label} {end}", fn, end)
            save(f"{label}_{end}.json", data)
            say("    shape:", shape(data))

        say("== history probe")
        for year in range(today.year - 1, 2014, -1):
            day = date(year, 6, 15)
            a = call(
                f"search_activities {year}",
                client.search_activities,
                limit=5,
                start_date=date(year, 1, 1),
                end_date=date(year, 12, 31),
            )
            n_acts = len(a) if isinstance(a, list) else shape(a)
            hrv = call(f"hrv_summaries {day}", client.get_daily_hrv_summaries, day, day + timedelta(days=6))
            ds = call(f"daily_summaries {day}", client.get_daily_summaries, day, day + timedelta(days=6))
            save(f"history/{year}.json", {"activities": a, "hrv": hrv, "daily": ds})
            say(f"  {year}: activities={n_acts} hrv={shape(hrv)[:60]} daily={shape(ds)[:60]}")


if __name__ == "__main__":
    main()
