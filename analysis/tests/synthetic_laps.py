"""Synthetic watch laps (`laps` table), as the importer writes them from the
FIT lap messages: cadence single-foot, numbered from 0.

Import with `from synthetic_laps import ...`.
"""

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Lap:
    distance_m: float
    timer_duration_s: float
    avg_hr_bpm: float | None = 150.0
    max_hr_bpm: float | None = 160.0
    avg_cadence: float | None = 85.0  # single-foot steps/min
    elevation_gain_m: float | None = None
    elevation_loss_m: float | None = None
    elapsed_duration_s: float | None = None  # defaults to timer_duration_s


def add_laps(conn: sqlite3.Connection, activity_id: int, laps: list[Lap]) -> None:
    """One `laps` row per lap, `avg_speed_mps` = distance / timer duration."""
    conn.executemany(
        "INSERT INTO laps (activity_id, lap_index, elapsed_duration_s, timer_duration_s,"
        " distance_m, avg_speed_mps, avg_hr_bpm, max_hr_bpm, avg_cadence,"
        " elevation_gain_m, elevation_loss_m) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                activity_id,
                i,
                lap.elapsed_duration_s or lap.timer_duration_s,
                lap.timer_duration_s,
                lap.distance_m,
                lap.distance_m / lap.timer_duration_s,
                lap.avg_hr_bpm,
                lap.max_hr_bpm,
                lap.avg_cadence,
                lap.elevation_gain_m,
                lap.elevation_loss_m,
            )
            for i, lap in enumerate(laps)
        ],
    )
    conn.commit()
