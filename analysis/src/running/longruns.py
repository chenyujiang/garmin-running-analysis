"""Long runs: efficiency factor (EF) and aerobic decoupling (Pa:HR).

Spec, "EF 与 decoupling"; formulas in the running-tool notes, section 6.

- Long run: a running activity (`RUNNING_TYPES`) whose Garmin duration is at
  least `MIN_DURATION_S` (60 min). All of them are listed.
- EF and decoupling only for outdoor road runs (`AEROBIC_TYPES`): GAP needs a
  real elevation profile, so treadmill and trail runs are listed with null EF.
- Steady seconds: the aerobic metric's steady-state filter
  (`running.aerobic.steady_state`: warm-up dropped, running, smoothed HR within
  `reference_hr` +- `hr_band_bpm`, speed stable, not right after a pause, no
  cadence lock), exactly as the spec defines steady state.
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

from running.aerobic import AEROBIC_TYPES, load_records, steady_state
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


def _per_run_ef(records: pl.DataFrame, config: Config) -> pl.DataFrame:
    df = steady_state(records, config.aerobic, config.run_walk)
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
                recs = load_records(db, road["activity_id"].to_list())
                efs = {}
                if not recs.is_empty():
                    efs = {r["activity_id"]: r for r in _per_run_ef(recs, config).to_dicts()}
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
            "稳态秒沿用有氧能力的规则：去掉前 "
            f"{a.warmup_s // 60} 分钟，在跑，平滑心率在 {a.reference_hr} ± "
            f"{a.hr_band_bpm:g} bpm 内，{a.speed_window_s} 秒内平滑速度变化 ≤ "
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
            "hr_band": {"reference_hr": a.reference_hr, "hr_band_bpm": a.hr_band_bpm},
            "activity_types": sorted(AEROBIC_TYPES),
            "listed_types": sorted(RUNNING_TYPES),
        },
    }
