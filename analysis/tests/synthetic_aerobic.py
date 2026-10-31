"""Synthetic runs with heart rate, barometric altitude and temperature, for the
aerobic metric (and anything else that needs HR, altitude and cadence per second).

Import with `from synthetic_aerobic import ...`. Builds on `synthetic.insert_activity`.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from synthetic import insert_activity


@dataclass(frozen=True)
class Stretch:
    """`seconds` of constant effort. `cadence` is single-foot (x2 = spm);
    `grade` is rise over horizontal distance; `hr=None` writes no heart rate."""

    seconds: int
    speed: float = 3.0
    hr: float | None = 145.0
    cadence: float = 85.0
    grade: float = 0.0


def steady(seconds: int, speed: float = 3.0, hr: float | None = 145.0, **kw) -> Stretch:
    return Stretch(seconds, speed=speed, hr=hr, **kw)


def add_hr_run(
    conn: sqlite3.Connection,
    activity_id: int,
    start_local: str,
    stretches: list[Stretch],
    activity_type: str = "running",
    temperature: float | None = 15.0,
    gps: bool = True,
    altitude: bool = True,
) -> None:
    """Activity row plus 1 Hz records (t = 0 .. total seconds). Each sample's
    speed covers the second ending at it; altitude follows distance x grade.
    `gps=False` writes no lat/lon and `altitude=False` no altitude, as on a
    treadmill-like run."""
    lat, lon = (10.0, 20.0) if gps else (None, None)
    duration = sum(s.seconds for s in stretches)
    distance_total = sum(s.seconds * s.speed for s in stretches)
    start_utc = insert_activity(
        conn,
        activity_id,
        start_local,
        activity_type,
        distance_m=distance_total,
        duration_s=float(duration),
    )
    t0 = datetime.strptime(start_utc, "%Y-%m-%dT%H:%M:%SZ")
    first = stretches[0]
    rows = [(0, first.hr, first.speed, first.cadence, 100.0, 0.0)]
    t, dist, alt = 0, 0.0, 100.0
    for s in stretches:
        for _ in range(s.seconds):
            t += 1
            dist += s.speed
            alt += s.speed * s.grade
            rows.append((t, s.hr, s.speed, s.cadence, alt, dist))
    conn.executemany(
        "INSERT INTO records (activity_id, timestamp, heart_rate, speed, cadence, altitude,"
        " distance, temperature, lat, lon) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                activity_id,
                (t0 + timedelta(seconds=sec)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                hr,
                v,
                c,
                a if altitude else None,
                d,
                temperature,
                lat,
                lon,
            )
            for sec, hr, v, c, a, d in rows
        ],
    )
    conn.commit()
