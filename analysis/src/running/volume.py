"""Weekly running volume: running-second distance of running-type activities,
by natural week (Monday to Sunday) of `start_time_local`, plus a rolling 7 days.

An activity counts entirely in the week (and day) it started, even if it runs
past midnight into the next week.
"""

from datetime import date, timedelta
from pathlib import Path
from typing import TypedDict

import polars as pl

from running.db import open_analysis_db
from running.runwalk import RUNNING_TYPES, empty_run_summaries, running_summaries
from running.section import Method, section_inputs

WEEKS = 12


class WeekVolume(TypedDict):
    week_start: str  # Monday, YYYY-MM-DD
    distance_m: float
    runs: int
    complete: bool  # False for the current, unfinished week


class RollingVolume(TypedDict):
    start: str  # first day included, YYYY-MM-DD
    end: str  # today, YYYY-MM-DD
    distance_m: float
    runs: int


class RunPace(TypedDict):
    activity_id: int
    activity_type: str
    start_time_local: str
    run_distance_m: float
    run_duration_s: float
    run_pace_s_per_km: float | None
    garmin_distance_m: float | None
    garmin_pace_s_per_km: float | None
    source: str  # "records": classified per second; "activity": Garmin totals (no cadence)


class Volume(TypedDict):
    today: str
    has_data: bool
    this_week: WeekVolume
    last_week: WeekVolume
    rolling_7d: RollingVolume
    weeks: list[WeekVolume]  # oldest first, the last one is this week
    runs: list[RunPace]  # running-type activities in the 12-week window, newest first
    garmin_totals_runs: int  # of those, runs without cadence (source "activity")
    method: Method


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def weekly_volume(today: date | None = None, root: Path | None = None) -> Volume:
    inputs = section_inputs(today, root)
    today = inputs.today
    settings = inputs.config.run_walk

    this_monday = week_start(today)
    first_monday = this_monday - timedelta(weeks=WEEKS - 1)
    rolling_start = today - timedelta(days=6)
    since = min(first_monday, rolling_start).isoformat()

    runs = empty_run_summaries()
    db = open_analysis_db(inputs.root)
    if db is not None:
        with db:
            runs = running_summaries(db, settings, since_local=since)
    runs = runs.with_columns(
        pl.col("start_time_local").str.slice(0, 10).str.to_date().alias("day")
    ).filter(pl.col("day") <= today)
    runs = runs.with_columns(pl.col("day").dt.truncate("1w").alias("week"))

    by_week = {
        row["week"]: (row["distance_m"], row["runs"])
        for row in runs.group_by("week")
        .agg(pl.col("run_distance_m").sum().alias("distance_m"), pl.len().alias("runs"))
        .iter_rows(named=True)
    }
    weeks: list[WeekVolume] = []
    for i in range(WEEKS):
        monday = first_monday + timedelta(weeks=i)
        distance, count = by_week.get(monday, (0.0, 0))
        weeks.append(
            {
                "week_start": monday.isoformat(),
                "distance_m": float(distance),
                "runs": int(count),
                "complete": monday != this_monday,
            }
        )

    rolling = runs.filter(pl.col("day") >= rolling_start)
    window = runs.filter(pl.col("day") >= first_monday).sort("start_time_local", descending=True)
    return {
        "today": today.isoformat(),
        "has_data": db is not None and not runs.is_empty(),
        "this_week": weeks[-1],
        "last_week": weeks[-2],
        "rolling_7d": {
            "start": rolling_start.isoformat(),
            "end": today.isoformat(),
            "distance_m": float(rolling["run_distance_m"].sum()),
            "runs": rolling.height,
        },
        "weeks": weeks,
        "runs": window.drop("day", "week", "garmin_duration_s").to_dicts(),
        "garmin_totals_runs": window.filter(pl.col("source") == "activity").height,
        "method": {
            "name": "跑的秒的距离，按自然周汇总",
            "description": (
                "只统计跑步类活动（路跑、跑步机、越野等）。步频 ×2 得到 spm，"
                f"按 {settings.smoothing_s} 秒滚动平均，≥ {settings.cadence_spm:g} spm 算跑；"
                f"连续走不到 {settings.min_walk_s} 秒的仍算跑；"
                f"两个采样点间隔超过 {settings.pause_gap_s} 秒视为暂停，不计时间和距离。"
                "周跑量只加跑的秒的距离。跑步配速 = 跑的秒的距离 ÷ 跑的秒的时长。"
                "按开始时间（当地时间）归入周一到周日的自然周，跨周的活动整次算在开始那一周。"
                "滚动 7 天是今天和之前 6 天。没有步频数据的活动用 Garmin 的总距离和总时长。"
            ),
            "params": {
                "cadence_spm": settings.cadence_spm,
                "smoothing_s": settings.smoothing_s,
                "min_walk_s": settings.min_walk_s,
                "pause_gap_s": settings.pause_gap_s,
                "week": "monday-sunday, start_time_local",
                "activity_types": sorted(RUNNING_TYPES),
            },
        },
    }
