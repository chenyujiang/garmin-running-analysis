"""One activity in detail: everything the `#/run/<id>` page needs, in one read.

Spec (run-detail), "running/detail.py". The response is the activity header
plus one key per section; each section is built by its own function from the
shared `DetailInputs` and carries its own `method` block. Sections:

- `summary` (ticket 02): distance, duration, running pace, Garmin pace,
  HR, cadence, elevation gain, air temperature.

Later sections register themselves in `SECTIONS` (one entry each) and keep
their builder in their own block below. Formulas are reused from `runwalk`,
`aerobic`, `load` and `longruns`, never copied.

Running-only fields of a non-running activity are null; the section's
`unavailable` dict maps each such field to its reason ("仅跑步类活动").
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import TypedDict

import polars as pl

from running.aerobic import air_temperature, load_records
from running.config import Config
from running.db import AnalysisDb, open_analysis_db
from running.runwalk import RUNNING_TYPES, classify_records, running_summaries
from running.section import Method, section_inputs

RUNNING_ONLY = "仅跑步类活动"


class ActivityHeader(TypedDict):
    activity_id: int
    activity_type: str
    activity_name: str | None
    start_time_local: str
    is_running: bool  # activity_type is one of RUNNING_TYPES


@dataclass
class DetailInputs:
    """What every section builder reads. `records` is loaded once, on first use."""

    db: AnalysisDb
    config: Config
    activity: dict  # the `activities` row
    is_running: bool

    @property
    def activity_id(self) -> int:
        return self.activity["activity_id"]

    @cached_property
    def records(self) -> pl.DataFrame:
        """Per-second records, classified run/walk (`runwalk.classify_records`):
        ts, heart_rate, speed, cadence, altitude, distance, spm, spm_smooth,
        dt_s, dd_m, running. `dt_s` is 0 for pauses and the first sample."""
        recs = load_records(self.db, [self.activity_id])
        return classify_records(recs, self.config.run_walk)


Section = Callable[[DetailInputs], dict]


def activity_detail(activity_id: int, root: Path | None = None) -> dict | None:
    """The detail page data, or None when there is no such activity (or no
    analysis database)."""
    inputs = section_inputs(None, root)
    db = open_analysis_db(inputs.root)
    if db is None:
        return None
    with db:
        if "activities" not in db.tables():
            return None
        rows = db.query("SELECT * FROM a.activities WHERE activity_id = ?", [activity_id])
        if rows.is_empty():
            return None
        row = rows.to_dicts()[0]
        d = DetailInputs(
            db=db,
            config=inputs.config,
            activity=row,
            is_running=row["activity_type"] in RUNNING_TYPES,
        )
        header: ActivityHeader = {
            "activity_id": row["activity_id"],
            "activity_type": row["activity_type"],
            "activity_name": row["activity_name"],
            "start_time_local": row["start_time_local"],
            "is_running": d.is_running,
        }
        return {"activity": header, **{key: build(d) for key, build in SECTIONS.items()}}


# --- summary (ticket 02) -----------------------------------------------------


def _weighted_mean(df: pl.DataFrame, col: str) -> float | None:
    """Mean of `col` weighted by `dt_s` over the samples that have a value
    (pauses and the first sample weigh nothing)."""
    v = df.filter(pl.col(col).is_not_null() & (pl.col("dt_s") > 0))
    weight = v["dt_s"].sum()
    if v.is_empty() or not weight:
        return None
    return float((v[col] * v["dt_s"]).sum() / weight)


def _summary(d: DetailInputs) -> dict:
    a, recs = d.activity, d.records
    unavailable: dict[str, str] = {}

    hr = recs.filter(pl.col("heart_rate").is_not_null())
    avg_hr = _weighted_mean(recs, "heart_rate") if not hr.is_empty() else a["avg_hr_bpm"]
    max_hr = float(hr["heart_rate"].max()) if not hr.is_empty() else a["max_hr_bpm"]

    run_pace = garmin_pace = cadence = None
    if d.is_running:
        summary = running_summaries(d.db, d.config.run_walk, activity_ids=[d.activity_id])
        if not summary.is_empty():
            run_pace = summary["run_pace_s_per_km"][0]
            garmin_pace = summary["garmin_pace_s_per_km"][0]
        cadence = _weighted_mean(recs.filter(pl.col("running")), "spm")
    else:
        for key in ("running_pace_s_per_km", "garmin_pace_s_per_km", "avg_cadence_spm"):
            unavailable[key] = RUNNING_ONLY

    temps = air_temperature(d.db, [d.activity_id])
    return {
        "distance_m": a["distance_m"],
        "duration_s": a["duration_s"],
        "running_pace_s_per_km": run_pace,
        "garmin_pace_s_per_km": garmin_pace,
        "avg_hr_bpm": avg_hr,
        "max_hr_bpm": max_hr,
        "avg_cadence_spm": cadence,
        "elevation_gain_m": a["elevation_gain_m"],
        "air_temperature_c": temps["temperature_c"][0] if not temps.is_empty() else None,
        "unavailable": unavailable,
        "method": _summary_method(d.config),
    }


def _summary_method(config: Config) -> Method:
    rw = config.run_walk
    return {
        "name": "概要",
        "description": (
            "距离和时长取 Garmin 记录的值。跑步配速只算跑的秒：步频（双脚）按 "
            f"{rw.smoothing_s} 秒平滑后 ≥ {rw.cadence_spm:g} spm 算跑，"
            f"短于 {rw.min_walk_s} 秒的走路仍算跑，采样间隔超过 {rw.pause_gap_s} 秒算暂停；"
            "没有步频数据时用 Garmin 的总距离和总时长。Garmin 平均配速包含走路，只作参照。"
            "平均心率按逐秒记录的时间加权（暂停不计），没有逐秒心率时取 Garmin 的值；"
            "最大心率取逐秒记录的最大值。平均步频只算跑的秒。累计爬升取 Garmin 的值。"
            "气温取 Open-Meteo 在活动中点时刻、离路线最近的网格点的逐时气温，前后两个整点线性插值。"
            "非跑步类活动不给跑步配速、Garmin 平均配速和步频。"
        ),
        "params": {
            "running_types": sorted(RUNNING_TYPES),
            "cadence_spm": rw.cadence_spm,
            "smoothing_s": rw.smoothing_s,
            "min_walk_s": rw.min_walk_s,
            "pause_gap_s": rw.pause_gap_s,
        },
    }


# --- per-second series (ticket 03) -------------------------------------------


# --- splits: laps and kilometres (ticket 04) ---------------------------------


# --- route shape (ticket 05) -------------------------------------------------


# --- run metrics: TRIMP, HR zones, aerobic value, EF (ticket 06) -------------


# --- section registry --------------------------------------------------------
# One entry per section, in page order. Each ticket adds its own line in its
# own slot; the comment lines between the slots keep parallel edits apart.

SECTIONS: dict[str, Section] = {
    "summary": _summary,
    # series (ticket 03)
    # splits (ticket 04)
    # route (ticket 05)
    # metrics (ticket 06)
}
