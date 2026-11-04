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
from datetime import date
from functools import cached_property
from pathlib import Path
from typing import TypedDict

import polars as pl

from running import aerobic, load, longruns
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
# Friel's running LTHR zones: TrainingPeaks, "Joe Friel's Quick Guide to
# Setting Zones" (2012, updated 2026): Z1 < 85 %, Z2 85-89 %, Z3 90-94 %,
# Z4 95-99 %, Z5a-c >= 100 % of LTHR. Z5a/b/c are one zone here.


def _hr_zones(d: DetailInputs, phys: load.Physiology | None) -> tuple[dict | None, str | None]:
    """Time in each zone over the seconds with a heart rate (pauses and the
    first sample weigh nothing), or None and the reason."""
    hr = d.records.filter(pl.col("heart_rate").is_not_null() & (pl.col("dt_s") > 0))
    if hr.is_empty():
        return None, "没有逐秒心率" if d.activity["avg_hr_bpm"] else "没有心率"
    if phys is None:
        return None, "该日期没有生效的生理参数"
    floors = [phys.lthr * p / 100.0 for p in d.config.zones.lthr_pct]
    bounds = [None, *floors]
    total = float(hr["dt_s"].sum())
    zones = []
    for k, low in enumerate(bounds):
        high = bounds[k + 1] if k + 1 < len(bounds) else None
        in_zone = pl.lit(True)
        if low is not None:
            in_zone &= pl.col("heart_rate") >= low
        if high is not None:
            in_zone &= pl.col("heart_rate") < high
        seconds = float(hr.filter(in_zone)["dt_s"].sum())
        zones.append(
            {
                "zone": k + 1,
                "low_bpm": low,
                "high_bpm": high,
                "seconds": seconds,
                "share": seconds / total,
            }
        )
    return {
        "lthr_bpm": phys.lthr,
        "physiology_effective_from": phys.effective_from.isoformat(),
        "lthr_pct": list(d.config.zones.lthr_pct),
        "total_s": total,
        "zones": zones,
    }, None


def _aerobic_value(d: DetailInputs) -> tuple[dict | None, str | None]:
    """This run's point on the aerobic trend (`aerobic.aerobic_runs`), or None
    and why the run does not count."""
    a, ae = d.activity, d.config.aerobic
    if not d.is_running:
        return None, RUNNING_ONLY
    if a["activity_type"] not in aerobic.AEROBIC_TYPES:
        return None, "不是户外路跑（跑步机和越野不计入）"
    start = a["start_time_local"]
    # "~" sorts after every digit, so [start, start~) holds only this start time.
    runs = aerobic.aerobic_runs(d.db, d.config, since_local=start, until_local=start + "~")
    row = runs.filter(pl.col("activity_id") == d.activity_id).to_dicts()
    if row and row[0]["valid"]:
        r = row[0]
        return {
            "speed_mps": r["speed_mps"],
            "pace_s_per_km": 1000.0 / r["speed_mps"],
            "steady_s": r["steady_s"],
            "mean_hr": r["mean_hr"],
            "reference_hr": ae.reference_hr,
        }, None
    if d.records.is_empty():
        return None, "没有逐秒记录"
    if d.records["heart_rate"].is_null().all():
        return None, "没有心率"
    if d.activity_id not in aerobic.gps_usable(d.db, [d.activity_id], ae):
        c = d.db.query(
            "SELECT count(lat) AS lat, count(lon) AS lon, count(altitude) AS alt,"
            " count(*) FILTER (WHERE speed > ?) AS fast FROM a.records WHERE activity_id = ?",
            [ae.max_speed_mps, d.activity_id],
        ).to_dicts()[0]
        if not c["lat"] or not c["lon"]:
            return None, "逐秒记录没有 GPS 位置（像跑步机）"
        if not c["alt"]:
            return None, "逐秒记录没有海拔"
        return None, (
            f"GPS 漂移：速度超过 {ae.max_speed_mps:g} m/s 的秒有 {c['fast']} 秒"
            f"（上限 {ae.max_fast_s} 秒）"
        )
    steady_s = row[0]["steady_s"] if row else 0.0
    return None, (f"稳态时间 {steady_s / 60:.0f} 分钟，不足 {ae.min_steady_s // 60} 分钟")


def _ef_value(d: DetailInputs, aerobic_why: str | None) -> tuple[dict | None, str | None]:
    """EF and decoupling as in the long-run table (`longruns._per_run_ef`).
    The gates are the aerobic value's (road run, `gps_usable`, enough steady
    time), so a run without an aerobic value has no EF, for the same reason."""
    if aerobic_why:
        return None, aerobic_why
    rows = longruns._per_run_ef(load_records(d.db, [d.activity_id]), d.config).to_dicts()
    e = rows[0] if rows else {}
    if not e.get("ef_first") or not e.get("ef_second"):
        return None, "稳态秒不够切成前后两半"
    long_enough = d.activity["duration_s"] >= longruns.MIN_DURATION_S
    dec = (e["ef_first"] - e["ef_second"]) / e["ef_first"] * 100.0 if long_enough else None
    return {
        "ef": e["ef"],
        "ef_first": e["ef_first"],
        "ef_second": e["ef_second"],
        "steady_s": e["steady_s"],
        "decoupling_pct": dec,
        "decoupling_high": dec is not None and dec > longruns.DECOUPLING_LIMIT_PCT,
    }, None


def _metrics(d: DetailInputs) -> dict:
    unavailable: dict[str, str] = {}
    aerobic_value, why = _aerobic_value(d)
    if why:
        unavailable["aerobic"] = why
    ef, why = _ef_value(d, why)
    if why:
        unavailable["ef"] = why
    if ef is None or ef["decoupling_pct"] is None:
        unavailable["decoupling"] = why or (
            f"不足 {longruns.MIN_DURATION_S // 60} 分钟，只给 EF，不算 decoupling"
        )
    phys = load.physiology_on(d.config, date.fromisoformat(d.activity["start_time_local"][:10]))
    zones, why = _hr_zones(d, phys)
    if why:
        unavailable["zones"] = why
    trimp = load.activity_trimp(d.db, d.config, d.activity)
    if trimp.value is None:
        unavailable["trimp"] = trimp.reason
    return {
        "trimp": trimp.value,
        "trimp_source": trimp.source,
        "zones": zones,
        "aerobic": aerobic_value,
        "ef": ef,
        "unavailable": unavailable,
        "method": _metrics_method(d.config),
    }


def _metrics_method(config: Config) -> Method:
    pct, a = config.zones.lthr_pct, config.aerobic
    return {
        "name": "本次指标",
        "description": (
            "TRIMP 和训练负荷页同一算法：Banister 逐秒累加，HRmax、HRrest 取活动日期"
            f"当时生效的生理参数，采样间隔最多按 {config.load.max_sample_gap_s} 秒计；"
            "没有逐秒心率时按摘要的平均心率和时长估算。"
            "心率区间按 Friel 的跑步 LTHR 区间分 5 区："
            f"Z1 < {pct[0]:g}%，Z2 {pct[0]:g}–{pct[1]:g}%，Z3 {pct[1]:g}–{pct[2]:g}%，"
            f"Z4 {pct[2]:g}–{pct[3]:g}%，Z5 ≥ {pct[3]:g}%（Friel 的 5a–5c 合为一区），"
            "每区含下限、不含上限。LTHR 取活动日期当时生效的那组生理参数。"
            "只统计有心率的秒，暂停不计。"
            "有氧能力值和有氧能力页同一算法：稳态秒的 GAP 速度按心率回归到 "
            f"{a.reference_hr} bpm；{aerobic.exclusions_note(a)}"
            "EF 和 decoupling 和长距离表同一算法：EF = 稳态秒平均 GAP 速度（m/min）÷ "
            "平均心率；decoupling 把稳态秒按累计时间对半分，(EF₁ − EF₂) ÷ EF₁ × 100%，"
            f"只给 {longruns.MIN_DURATION_S // 60} 分钟及以上的活动，"
            f"超过 {longruns.DECOUPLING_LIMIT_PCT:g}% 标红。"
            "不计入有氧能力的活动也不给 EF。"
        ),
        "params": {
            "lthr_pct": list(pct),
            "max_sample_gap_s": config.load.max_sample_gap_s,
            "reference_hr": a.reference_hr,
            "min_steady_s": a.min_steady_s,
            "min_duration_s": longruns.MIN_DURATION_S,
            "decoupling_limit_pct": longruns.DECOUPLING_LIMIT_PCT,
            "ef_unit": "m/min per bpm",
        },
    }


# --- section registry --------------------------------------------------------
# One entry per section, in page order. Each ticket adds its own line in its
# own slot; the comment lines between the slots keep parallel edits apart.

SECTIONS: dict[str, Section] = {
    "summary": _summary,
    # series (ticket 03)
    # splits (ticket 04)
    # route (ticket 05)
    # metrics (ticket 06)
    "metrics": _metrics,
}
