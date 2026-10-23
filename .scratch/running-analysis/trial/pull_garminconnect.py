"""Trial pull via the unofficial garminconnect library (ticket 03).

Run interactively in your own terminal: it asks for email and password once,
never stores the password, and saves only the session tokens to ~/.garminconnect.
Requests are serial with a long pause to stay well clear of rate limits.
"""

import getpass
import json
import time
from datetime import date
from pathlib import Path

from garminconnect import Garmin

TOKENSTORE = str(Path.home() / ".garminconnect")
OUT = Path(__file__).resolve().parent / "data" / "garminconnect"
PAUSE_S = 5
# Same runs as the Personal API pull, so the FIT files can be compared.
ACTIVITY_IDS = [10000000003, 10000000002, 10000000001]


def save(name: str, data) -> None:
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def step(label: str, fn, *args, **kwargs):
    t0 = time.perf_counter()
    try:
        result = fn(*args, **kwargs)
        size = len(result) if isinstance(result, bytes) else len(json.dumps(result))
        print(f"  {label}: {time.perf_counter() - t0:.2f}s, {size} bytes", flush=True)
    except Exception as err:  # report and keep going: this is a probe
        result = None
        print(f"  ! {label}: {type(err).__name__}: {err}", flush=True)
    time.sleep(PAUSE_S)
    return result


def login() -> Garmin:
    try:
        api = Garmin()
        api.login(TOKENSTORE)
        print("login: reused saved tokens")
        return api
    except Exception:
        pass
    email = input("Garmin email: ")
    password = getpass.getpass("Garmin password (not stored): ")
    t0 = time.perf_counter()
    api = Garmin(email, password)
    api.login()
    del password
    api.client.dump(TOKENSTORE)
    print(f"login: {time.perf_counter() - t0:.2f}s, tokens saved to {TOKENSTORE}")
    return api


def main() -> None:
    api = login()
    today = date.today().isoformat()
    save("training_status.json", step("get_training_status", api.get_training_status, today))
    save("max_metrics.json", step("get_max_metrics", api.get_max_metrics, today))
    save("race_predictions.json", step("get_race_predictions", api.get_race_predictions))
    for aid in ACTIVITY_IDS:
        blob = step(f"download ORIGINAL {aid}", api.download_activity, str(aid), dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)
        if blob:
            save(f"activities/{aid}.zip", blob)
    print("done")


if __name__ == "__main__":
    main()
