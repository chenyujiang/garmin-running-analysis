"""Synthetic runs with a GPS track, for the route shape (run-detail ticket 05).

Import with `from synthetic_route import ...`. Builds on `synthetic.insert_activity`.
The coordinates come from the calling test, which keeps them fictional.
"""

import sqlite3
from datetime import datetime, timedelta

from synthetic import insert_activity

LatLon = tuple[float, float] | None


def add_route_run(
    conn: sqlite3.Connection,
    activity_id: int,
    start_local: str,
    track: list[LatLon],
    activity_type: str = "running",
    speed: float = 3.0,
) -> None:
    """Activity row plus one record per `track` entry, one second apart, at a
    steady `speed`, 145 bpm and 170 spm. A `None` entry is a second without a
    GPS fix (lat and lon null)."""
    seconds = len(track) - 1
    start_utc = insert_activity(
        conn,
        activity_id,
        start_local,
        activity_type,
        distance_m=seconds * speed,
        duration_s=float(seconds),
    )
    t0 = datetime.strptime(start_utc, "%Y-%m-%dT%H:%M:%SZ")
    conn.executemany(
        "INSERT INTO records (activity_id, timestamp, heart_rate, speed, cadence, distance,"
        " lat, lon) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                activity_id,
                (t0 + timedelta(seconds=t)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                145.0,
                speed,
                85.0,
                t * speed,
                *(fix if fix is not None else (None, None)),
            )
            for t, fix in enumerate(track)
        ],
    )
    conn.commit()
