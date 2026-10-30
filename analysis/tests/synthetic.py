"""Helpers that write synthetic activities and per-second records into a test
analysis database (see the `analysis_db` fixture in conftest.py).

Import with `from synthetic import ...`; pytest puts `tests/` on sys.path.
"""

import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# (seconds, cadence in single-foot steps/min as stored by FIT, speed in m/s)
Segment = tuple[int, float | None, float | None]

RUN: tuple[float, float] = (85.0, 3.0)  # 170 spm, 3.0 m/s (5:33/km)
WALK: tuple[float, float] = (55.0, 1.4)  # 110 spm
STOP: tuple[float, float] = (0.0, 0.0)


def run(seconds: int) -> Segment:
    return (seconds, *RUN)


def walk(seconds: int) -> Segment:
    return (seconds, *WALK)


def stop(seconds: int) -> Segment:
    return (seconds, *STOP)


def pause(seconds: int) -> Segment:
    """The watch is paused: time passes with no samples until the resume sample."""
    return (seconds, None, None)


def insert_activity(
    conn: sqlite3.Connection,
    activity_id: int,
    start_local: str,
    activity_type: str = "running",
    *,
    tz: str = "Pacific/Auckland",
    distance_m: float | None = None,
    duration_s: float | None = None,
    avg_speed_mps: float | None = None,
) -> str:
    """Insert one `activities` row. `start_local` is wall clock ("2026-10-26T07:00:00").
    Returns `start_time_utc` (ISO with Z)."""
    local = datetime.fromisoformat(start_local).replace(tzinfo=ZoneInfo(tz))
    start_utc = local.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    if avg_speed_mps is None and distance_m and duration_s:
        avg_speed_mps = distance_m / duration_s
    conn.execute(
        "INSERT INTO activities (activity_id, activity_type, start_time_utc, start_time_local,"
        " time_zone, distance_m, duration_s, avg_speed_mps) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            activity_id,
            activity_type,
            start_utc,
            start_local,
            tz,
            distance_m,
            duration_s,
            avg_speed_mps,
        ),
    )
    conn.commit()
    return start_utc


def insert_records(
    conn: sqlite3.Connection, activity_id: int, start_utc: str, segments: list[Segment]
) -> None:
    """Write 1 Hz `records` for the segments. A first sample at t=0 (distance 0)
    is followed by one sample per second; each sample's speed covers the second
    that ends at it, so the total duration is exactly the sum of the segments.
    A `pause` segment skips time and writes one resume sample at its end."""
    t0 = datetime.strptime(start_utc, "%Y-%m-%dT%H:%M:%SZ")
    first_cadence, first_speed = segments[0][1], segments[0][2]
    rows = [(0, first_cadence, first_speed, 0.0)]
    t, dist = 0, 0.0
    for seconds, cadence, speed in segments:
        if cadence is None and speed is None:
            # Resume: one sample at the end of the pause, distance unchanged.
            t += seconds
            rows.append((t, rows[-1][1], rows[-1][2], dist))
            continue
        for _ in range(seconds):
            t += 1
            dist += speed or 0.0
            rows.append((t, cadence, speed, dist))
    conn.executemany(
        "INSERT INTO records (activity_id, timestamp, cadence, speed, distance)"
        " VALUES (?, ?, ?, ?, ?)",
        [
            (
                activity_id,
                (t0 + timedelta(seconds=s)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                c,
                v,
                d,
            )
            for s, c, v, d in rows
        ],
    )
    conn.commit()


def add_run(
    conn: sqlite3.Connection,
    activity_id: int,
    start_local: str,
    segments: list[Segment],
    activity_type: str = "running",
) -> None:
    """Activity row plus records; the activity totals are the Garmin-style
    totals over the whole recording, walking included."""
    duration = sum(s[0] for s in segments if s[2] is not None)
    distance = sum(s[0] * (s[2] or 0.0) for s in segments)
    start_utc = insert_activity(
        conn,
        activity_id,
        start_local,
        activity_type,
        distance_m=distance,
        duration_s=float(duration),
    )
    insert_records(conn, activity_id, start_utc, segments)
