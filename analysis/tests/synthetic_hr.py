"""Helpers for the training-load tests (ticket 09): activities plus `records`
with heart rate, in a test analysis database (the `analysis_db` fixture).
Import with `from synthetic_hr import ...`."""

import sqlite3
from collections.abc import Callable
from datetime import date, datetime, timedelta


def insert_activity(
    conn: sqlite3.Connection,
    activity_id: int,
    day: date | str,
    *,
    hour: int = 7,
    activity_type: str = "running",
    duration_s: float = 3600.0,
    distance_m: float = 10000.0,
    utc_offset_h: int = 0,
    avg_hr_bpm: float | None = None,
) -> datetime:
    """Insert one `activities` row starting at `hour` local time on `day`.
    Returns the UTC start time (naive)."""
    day = date.fromisoformat(day) if isinstance(day, str) else day
    local = datetime(day.year, day.month, day.day, hour)
    utc = local - timedelta(hours=utc_offset_h)
    conn.execute(
        "INSERT INTO activities (activity_id, activity_type, activity_name, start_time_utc,"
        " start_time_local, distance_m, duration_s, avg_hr_bpm) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            activity_id,
            activity_type,
            f"活动 {activity_id}",
            utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            local.strftime("%Y-%m-%dT%H:%M:%S"),
            distance_m,
            duration_s,
            avg_hr_bpm,
        ),
    )
    conn.commit()
    return utc


def insert_records(
    conn: sqlite3.Connection,
    activity_id: int,
    start_utc: datetime,
    seconds: int,
    heart_rate: int | None | Callable[[int], int | None],
    *,
    every_s: int = 1,
) -> None:
    """Insert `records` rows every `every_s` seconds for `seconds` seconds.
    `heart_rate` is a constant, None (no HR), or a function of the offset in s."""
    rows = []
    for t in range(0, seconds, every_s):
        hr = heart_rate(t) if callable(heart_rate) else heart_rate
        ts = (start_utc + timedelta(seconds=t)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows.append((activity_id, ts, hr))
    conn.executemany(
        "INSERT INTO records (activity_id, timestamp, heart_rate) VALUES (?, ?, ?)", rows
    )
    conn.commit()


def insert_run(
    conn: sqlite3.Connection,
    activity_id: int,
    day: date | str,
    heart_rate: int | None | Callable[[int], int | None],
    *,
    seconds: int = 3600,
    every_s: int = 1,
    **activity,
) -> None:
    """An activity plus its per-second records at `heart_rate`."""
    start = insert_activity(conn, activity_id, day, duration_s=seconds, **activity)
    insert_records(conn, activity_id, start, seconds, heart_rate, every_s=every_s)
