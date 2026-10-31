"""Synthetic runs with heart rate and barometric altitude, plus hourly air
temperature, for the aerobic metric (and anything else that needs HR, altitude
and cadence per second).

Import with `from synthetic_aerobic import ...`. Builds on `synthetic.insert_activity`.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from synthetic import insert_activity

# A made-up running spot and the 0.1 degree grid point it rounds to.
POSITION: tuple[float, float] = (10.02, 20.03)
GRID: tuple[float, float] = (10.0, 20.0)


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
    gps: bool = True,
    altitude: bool = True,
    position: tuple[float, float] = POSITION,
) -> str:
    """Activity row plus 1 Hz records (t = 0 .. total seconds) at a fixed
    `position`. Each sample's speed covers the second ending at it; altitude
    follows distance x grade. `gps=False` writes no lat/lon and
    `altitude=False` no altitude, as on a treadmill-like run. Returns
    `start_time_utc`."""
    lat, lon = position if gps else (None, None)
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
        " distance, lat, lon) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                activity_id,
                (t0 + timedelta(seconds=sec)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                hr,
                v,
                c,
                a if altitude else None,
                d,
                lat,
                lon,
            )
            for sec, hr, v, c, a, d in rows
        ],
    )
    conn.commit()
    return start_utc


def add_hourly_weather(
    conn: sqlite3.Connection,
    hours: dict[str, float | None],
    grid: tuple[float, float] = GRID,
) -> None:
    """`hourly_weather` rows for one grid point: {"2026-10-19T18:00:00Z": 12.0}."""
    conn.executemany(
        "INSERT INTO hourly_weather (grid_lat, grid_lon, time_utc, temperature_c)"
        " VALUES (?, ?, ?, ?)",
        [(grid[0], grid[1], t, c) for t, c in hours.items()],
    )
    conn.commit()


def utc_hours(start_utc: str, temps: list[float | None]) -> dict[str, float | None]:
    """Consecutive whole hours from `start_utc` (ISO with Z, on the hour)."""
    t0 = datetime.strptime(start_utc, "%Y-%m-%dT%H:%M:%SZ")
    return {
        (t0 + timedelta(hours=k)).strftime("%Y-%m-%dT%H:%M:%SZ"): c for k, c in enumerate(temps)
    }
