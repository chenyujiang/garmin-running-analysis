"""Second probe (ticket 03): earliest activity, wellness start date, HRV/sleep coverage.

Reuses the key loading and logging helpers from pull_personal_api.py.
"""

import json
from datetime import date, timedelta

import pull_personal_api as p
from garmin_personal_api import GarminPersonalApiClient, PersonalApiAuthenticator


def main() -> None:
    with PersonalApiAuthenticator() as auth:
        token = auth.obtain_token(p.KEY)
    p.SECRETS.append(token.access_token)
    today = date.today()

    with GarminPersonalApiClient(token.access_token) as client:
        p.say("== earliest activities (2021)")
        acts, start = [], 0
        while True:
            page = p.call(
                f"search_activities 2021 start={start}",
                client.search_activities,
                start=start,
                limit=100,
                start_date=date(2021, 1, 1),
                end_date=date(2021, 12, 31),
            ) or []
            acts.extend(page)
            if len(page) < 100:
                break
            start += 100
        p.save("history/activities_2021_all.json", acts)
        dates = sorted(a["startTimeLocal"] for a in acts)
        p.say(f"  2021 count={len(acts)} earliest={dates[:3]}")
        p.say("  types:", sorted({a["activityType"]["typeKey"] for a in acts}))

        p.say("== activity search without date filter, deep offset")
        for start in (500, 1000, 1500):
            page = p.call(f"search_activities start={start}", client.search_activities, start=start, limit=1) or []
            p.say(f"  start={start}: {[a['startTimeLocal'] for a in page]}")

        p.say("== wellness start: first day of each quarter")
        for year in range(2021, today.year + 1):
            for month in (1, 4, 7, 10):
                day = date(year, month, 1)
                if day > today:
                    break
                ds = p.call(f"daily_summaries {day}", client.get_daily_summaries, day, day) or {}
                rows = ds.get("data", []) if isinstance(ds, dict) else []
                rhr = rows[0].get("heartRate", {}).get("restingValue") if rows else None
                p.say(f"    {day}: rows={len(rows)} restingHR={'yes' if rhr else 'no'}")

        p.say("== HRV / sleep: last 30 days, day by day")
        hrv_days = sleep_days = 0
        for i in range(1, 31):
            day = today - timedelta(days=i)
            hrv = p.call(f"daily_hrv {day}", client.get_daily_hrv, day)
            sleep = p.call(f"daily_sleep {day}", client.get_daily_sleep, day)
            p.save(f"health/{day}.json", {"hrv": hrv, "sleep": sleep})
            hrv_days += hrv is not None
            sleep_days += bool(isinstance(sleep, dict) and sleep.get("sleepTimeSeconds"))
        p.say(f"  days with HRV: {hrv_days}/30, days with sleep: {sleep_days}/30")
        sl = p.call("sleep_summaries 30d", client.get_daily_sleep_summaries, today - timedelta(days=30), today)
        p.say("  sleep_summaries 30d:", p.shape(sl)[:200])


if __name__ == "__main__":
    main()
