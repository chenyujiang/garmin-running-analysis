"""Long runs: efficiency factor (EF) and aerobic decoupling (Pa:HR).

Spec, "EF 与 decoupling"; formulas in the running-tool notes, section 6.

- Long run: a running activity (`RUNNING_TYPES`) whose Garmin duration is at
  least `MIN_DURATION_S` (60 min). All of them are listed.
- EF and decoupling only for outdoor road runs (`AEROBIC_TYPES`): GAP needs a
  real elevation profile, so treadmill and trail runs are listed with null EF.
  Road runs that fail `running.aerobic.gps_usable` (no position or altitude,
  or GPS drift) are listed with null EF too.
- Steady seconds: the aerobic metric's steady-state filter without its heart
  rate band (`running.aerobic.steady_state(..., hr_band=False)`: warm-up
  dropped, running, speed stable, not right after a pause, no cadence lock).
  The band would cut away the seconds a drifting heart rate leaves it, and
  with them the drift decoupling is meant to show.
- EF = time-weighted mean GAP speed (m/min) / time-weighted mean smoothed HR,
  over the steady seconds. Unit: m/min per bpm (Friel's yd/min per bpm value is
  this / 0.9144). GAP uses Minetti 2002 instead of TrainingPeaks' NGP, so the
  numbers are not directly comparable with TrainingPeaks.
- Decoupling: the steady seconds are cut in half by cumulative steady time;
  decoupling% = (EF_1 - EF_2) / EF_1 x 100. Above `DECOUPLING_LIMIT_PCT` (5%)
  is flagged; negative values are fine.
- Fewer than `Aerobic.min_steady_s` steady seconds: EF and decoupling are null.
"""

from datetime import date, timedelta
from pathlib import Path
from typing import TypedDict

import polars as pl

from running.aerobic import (
    AEROBIC_TYPES,
    exclusions_note,
    gps_usable,
    load_records,
    steady_state,
)
from running.config import Config
from running.db import AnalysisDb, open_analysis_db
from running.runwalk import RUNNING_TYPES
from running.section import Method, section_inputs

MIN_DURATION_S = 3600
DECOUPLING_LIMIT_PCT = 5.0
DEFAULT_LIMIT = 10


class LongRun(TypedDict):
    activity_id: int
    activity_type: str
    start_time_local: str
    distance_m: float | None
    duration_s: float
    steady_s: float
    ef: float | None  # m/min per bpm; null for treadmill/trail runs
    ef_first: float | None
    ef_second: float | None
    decoupling_pct: float | None
    decoupling_high: bool


class LongRuns(TypedDict):
    today: str
    has_data: bool
    runs: list[LongRun]  # newest first
    method: Method


def _long_run_rows(db: AnalysisDb, until_local: str, limit: int) -> pl.DataFrame:
    types = sorted(RUNNING_TYPES)
    return db.query(
        "SELECT activity_id, activity_type, start_time_local, distance_m, duration_s"
        " FROM a.activities"
        f" WHERE activity_type IN ({', '.join('?' for _ in types)})"
        " AND duration_s >= ? AND start_time_local < ?"
        " ORDER BY start_time_local DESC LIMIT ?",
        [*types, MIN_DURATION_S, until_local, limit],
    )


def _ef(gap: pl.Expr, hr: pl.Expr, dt: pl.Expr) -> pl.Expr:
    """Time-weighted mean GAP (m/min) over time-weighted mean HR."""
    return ((gap * dt).sum() * 60.0) / (hr * dt).sum()


def per_run_ef(records: pl.DataFrame, config: Config) -> pl.DataFrame:
    df = steady_state(records, config.aerobic, config.run_walk, hr_band=False)
    df = df.filter(pl.col("steady")).sort("activity_id", "ts")
    df = df.with_columns(
        pl.col("dt_s").cum_sum().over("activity_id").alias("_cum"),
        pl.col("dt_s").sum().over("activity_id").alias("_total"),
    )
    first = pl.col("_cum") <= pl.col("_total") / 2
    gap, hr, dt = pl.col("gap_mps"), pl.col("hr_smooth"), pl.col("dt_s")
    return df.group_by("activity_id").agg(
        dt.sum().alias("steady_s"),
        _ef(gap, hr, dt).alias("ef"),
        _ef(gap.filter(first), hr.filter(first), dt.filter(first)).alias("ef_first"),
        _ef(gap.filter(~first), hr.filter(~first), dt.filter(~first)).alias("ef_second"),
    )


_EF_SCHEMA = {
    "activity_id": pl.Int64,
    "steady_s": pl.Float64,
    "ef": pl.Float64,
    "ef_first": pl.Float64,
    "ef_second": pl.Float64,
}

# EF results (`_road_ef`) by activity: each run depends only on its own
# records, so a run is computed once and reused until the database file or
# its WAL changes, or the aerobic / run-walk settings do. Kept per database path.
_EF_CACHE: dict[Path, tuple[tuple, pl.DataFrame]] = {}


def _cached_ef(db: AnalysisDb, config: Config, activity_ids: list[int]) -> pl.DataFrame:
    key = (db.file_version(), config.aerobic, config.run_walk)
    path = db.path.resolve()
    cached = _EF_CACHE.get(path)
    known = cached[1] if cached is not None and cached[0] == key else None
    if known is None:
        known = pl.DataFrame(schema=_EF_SCHEMA)
    missing = sorted(set(activity_ids) - set(known["activity_id"].to_list()))
    if missing:
        # Runs without usable GPS or records get a row of nulls, so they are
        # not read again.
        fresh = (
            pl.DataFrame({"activity_id": missing}, schema={"activity_id": pl.Int64})
            .join(_road_ef(db, config, missing), on="activity_id", how="left")
            .select(_EF_SCHEMA.keys())
            .cast(_EF_SCHEMA)
        )
        known = pl.concat([known, fresh])
        _EF_CACHE[path] = (key, known)
    return known.filter(pl.col("activity_id").is_in(activity_ids))


def _road_ef(db: AnalysisDb, config: Config, activity_ids: list[int]) -> pl.DataFrame:
    """`per_run_ef` for the road runs among `activity_ids` that pass `gps_usable`."""
    usable = gps_usable(db, activity_ids, config.aerobic)
    recs = load_records(db, sorted(usable))
    if recs.is_empty():
        return pl.DataFrame(schema=_EF_SCHEMA)
    return per_run_ef(recs, config)


def long_runs(
    today: date | None = None, limit: int = DEFAULT_LIMIT, root: Path | None = None
) -> LongRuns:
    inputs = section_inputs(today, root)
    today, config = inputs.today, inputs.config
    min_steady_s = config.aerobic.min_steady_s
    until = (today + timedelta(days=1)).isoformat()

    runs: list[LongRun] = []
    db = open_analysis_db(inputs.root)
    if db is not None:
        with db:
            if "activities" in db.tables():
                acts = _long_run_rows(db, until, limit)
                road = acts.filter(pl.col("activity_type").is_in(sorted(AEROBIC_TYPES)))
                road_ids = road["activity_id"].to_list()
                efs = {r["activity_id"]: r for r in _cached_ef(db, config, road_ids).to_dicts()}
                for a in acts.iter_rows(named=True):
                    e = efs.get(a["activity_id"], {})
                    steady_s = float(e.get("steady_s") or 0.0)
                    ok = steady_s >= min_steady_s and e.get("ef_first") and e.get("ef_second")
                    ef1 = e["ef_first"] if ok else None
                    ef2 = e["ef_second"] if ok else None
                    dec = (ef1 - ef2) / ef1 * 100.0 if ok else None
                    runs.append(
                        {
                            "activity_id": a["activity_id"],
                            "activity_type": a["activity_type"],
                            "start_time_local": a["start_time_local"],
                            "distance_m": a["distance_m"],
                            "duration_s": a["duration_s"],
                            "steady_s": steady_s,
                            "ef": e["ef"] if ok else None,
                            "ef_first": ef1,
                            "ef_second": ef2,
                            "decoupling_pct": dec,
                            "decoupling_high": dec is not None and dec > DECOUPLING_LIMIT_PCT,
                        }
                    )
    return {
        "today": today.isoformat(),
        "has_data": bool(runs),
        "runs": runs,
        "method": _method(config),
    }


def _method(config: Config) -> Method:
    a = config.aerobic
    return {
        "name": "EF 与 decoupling（Pa:HR）",
        "description": (
            f"列出 {MIN_DURATION_S // 60} 分钟及以上的跑步"
            "（按 Garmin 记录的时长，含跑步机和越野）。"
            "EF 和 decoupling 只算户外路跑：跑步机和越野没有可靠的坡度，GAP 不准，留空。"
            f"同有氧能力：{exclusions_note(a)}"
            "稳态秒沿用有氧能力的规则，但不限心率（心率带会把漂移出带的秒剔掉，"
            "decoupling 就看不出漂移）：去掉前 "
            f"{a.warmup_s // 60} 分钟，在跑，{a.speed_window_s} 秒内平滑速度变化 ≤ "
            f"{a.max_speed_change:.0%}，不是暂停后的第一秒，心率与 spm 相差 ≥ "
            f"{a.min_hr_spm_gap:g}。"
            "EF = 平均 GAP 速度（m/min）÷ 平均心率（bpm），只用稳态秒，按时间加权；"
            "GAP 用 Minetti 2002，不是 TrainingPeaks 的 NGP，数值不能直接对比。"
            "单位是 m/min/bpm，Friel 用的码/分 ÷ bpm 要再除以 0.9144。"
            "decoupling：把稳态秒按累计时间对半分，分别算 EF₁、EF₂，"
            "decoupling = (EF₁ − EF₂) ÷ EF₁ × 100%。"
            f"超过 {DECOUPLING_LIMIT_PCT:g}% 标红（Friel：≤5% 说明有氧耐力足够）；"
            "负值表示后半程更省力，不标红。"
            f"稳态时间不足 {a.min_steady_s // 60} 分钟的跑步不给 EF 和 decoupling。"
        ),
        "params": {
            "min_duration_s": MIN_DURATION_S,
            "decoupling_limit_pct": DECOUPLING_LIMIT_PCT,
            "ef_unit": "m/min per bpm",
            "split": "steady seconds, halved by cumulative steady time",
            "min_steady_s": a.min_steady_s,
            "warmup_s": a.warmup_s,
            "smoothing_s": a.smoothing_s,
            "speed_window_s": a.speed_window_s,
            "max_speed_change": a.max_speed_change,
            "min_hr_spm_gap": a.min_hr_spm_gap,
            "max_speed_mps": a.max_speed_mps,
            "max_fast_s": a.max_fast_s,
            "activity_types": sorted(AEROBIC_TYPES),
            "listed_types": sorted(RUNNING_TYPES),
        },
    }
