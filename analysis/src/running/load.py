"""Training load: per-second Banister TRIMP, CTL/ATL/TSB.

Formula sources and the choice of recursion are recorded in
`.scratch/running-tool/issues/09-training-load.md`.

- TRIMP per activity = Σ Δt[min] · x · 0.64 · e^(1.92·x) over records with a
  heart rate, x = (HR − HRrest) / (HRmax − HRrest) clamped to [0, 1], using
  the physiology set in effect on the activity's local start date. Δt is the
  gap to the next record, capped at MAX_SAMPLE_GAP_S (pauses do not count);
  the last record counts 1 s. Activities without heart-rate records are
  missing, not estimated, and add nothing to the daily load.
- Daily load = sum of TRIMP of activities starting that local day.
- CTL/ATL: EWMA with the 1/N recursion, X_t = X_{t−1} + (Load_t − X_{t−1}) / N,
  N = 42 / 7, starting at 0 on the first activity day, rest days Load = 0.
- TSB_t = CTL_{t−1} − ATL_{t−1} (TrainingPeaks "Form": yesterday's values).
- Load spike: ATL/CTL > 1.5 on the current day.
"""

import math
from datetime import date, timedelta
from pathlib import Path
from typing import TypedDict

import polars as pl

from running.config import Config, ConfigError, Physiology, data_dir, load_config
from running.db import AnalysisDb, open_analysis_db

# Banister TRIMP, male coefficients (Banister & Calvert 1980; b from Morton,
# Fitz-Clarke & Banister 1990).
TRIMP_A = 0.64
TRIMP_B = 1.92
CTL_DAYS = 42
ATL_DAYS = 7
SPIKE_RATIO = 1.5
SERIES_DAYS = 84  # 12 weeks
MAX_SAMPLE_GAP_S = 10.0


def heart_rate_reserve(hr: float, hr_rest: float, hr_max: float) -> float:
    """x = (HR − HRrest) / (HRmax − HRrest), clamped to [0, 1]."""
    x = (hr - hr_rest) / (hr_max - hr_rest)
    return min(1.0, max(0.0, x))


def banister_trimp(minutes: float, hr: float, hr_rest: float, hr_max: float) -> float:
    """Banister TRIMP for `minutes` at a constant heart rate:
    D · x · 0.64 · e^(1.92·x)."""
    x = heart_rate_reserve(hr, hr_rest, hr_max)
    return minutes * x * TRIMP_A * math.exp(TRIMP_B * x)


def physiology_on(config: Config, day: date) -> Physiology | None:
    """The physiology set in effect on `day`: the latest `effective_from` ≤ day."""
    eligible = [p for p in config.physiology if p.effective_from <= day]
    return max(eligible, key=lambda p: p.effective_from) if eligible else None


class LoadPoint(TypedDict):
    date: str
    trimp: float
    ctl: float
    atl: float
    tsb: float


class MissingActivity(TypedDict):
    activity_id: int
    date: str
    name: str | None
    activity_type: str
    reason: str


class LoadMethod(TypedDict):
    trimp: str
    trimp_formula: str
    trimp_a: float
    trimp_b: float
    hr_rest: int | None
    hr_max: int | None
    physiology_effective_from: str | None
    max_sample_gap_s: float
    ctl_days: int
    atl_days: int
    recursion: str
    recursion_formula: str
    tsb_formula: str
    spike_ratio: float


class LoadCurrent(TypedDict):
    date: str
    ctl: float
    atl: float
    tsb: float
    ratio: float | None


class TrainingLoad(TypedDict):
    as_of: str
    has_data: bool
    current: LoadCurrent | None
    spike: bool
    spike_since: str | None
    series: list[LoadPoint]
    missing_hr_count: int
    missing_hr_recent: list[MissingActivity]
    config_error: str | None
    method: LoadMethod


def _method(phys: Physiology | None) -> LoadMethod:
    return {
        "trimp": "Banister TRIMP（逐秒，男性系数）",
        "trimp_formula": (
            "TRIMP = Σ Δt[min] · x · 0.64 · e^(1.92·x)，x = (HR − HRrest) / (HRmax − HRrest)"
        ),
        "trimp_a": TRIMP_A,
        "trimp_b": TRIMP_B,
        "hr_rest": phys.hr_rest if phys else None,
        "hr_max": phys.hr_max if phys else None,
        "physiology_effective_from": phys.effective_from.isoformat() if phys else None,
        "max_sample_gap_s": MAX_SAMPLE_GAP_S,
        "ctl_days": CTL_DAYS,
        "atl_days": ATL_DAYS,
        "recursion": "1/N",
        "recursion_formula": "今天 = 昨天 + (当天 TRIMP − 昨天) / N",
        "tsb_formula": "TSB = 昨天的 CTL − 昨天的 ATL",
        "spike_ratio": SPIKE_RATIO,
    }


_HR_SECONDS_SQL = f"""
WITH r AS (
    SELECT activity_id, heart_rate,
           epoch(CAST(rtrim(timestamp, 'Z') AS TIMESTAMP)) AS t
    FROM a.records
), d AS (
    SELECT activity_id, heart_rate,
           least(greatest(coalesce(
               lead(t) OVER (PARTITION BY activity_id ORDER BY t) - t, 1.0), 0.0),
               {MAX_SAMPLE_GAP_S}) AS dt
    FROM r
)
SELECT activity_id, heart_rate AS hr, sum(dt) AS seconds
FROM d WHERE heart_rate IS NOT NULL AND heart_rate > 0
GROUP BY activity_id, heart_rate
"""


def _activity_trimp(
    db: AnalysisDb, config: Config, as_of: date
) -> tuple[dict[date, float], list[MissingActivity]]:
    """Daily TRIMP up to `as_of`, and activities with missing TRIMP."""
    activities = db.query(
        "SELECT activity_id, activity_type, activity_name AS name,"
        " CAST(substr(start_time_local, 1, 10) AS DATE) AS day FROM a.activities"
        " WHERE CAST(substr(start_time_local, 1, 10) AS DATE) <= ? ORDER BY start_time_local",
        [as_of],
    )
    hr = db.query(_HR_SECONDS_SQL) if "records" in db.tables() else pl.DataFrame()
    per_activity: dict[int, list[tuple[float, float]]] = {}
    for row in hr.iter_rows(named=True):
        per_activity.setdefault(row["activity_id"], []).append((row["hr"], row["seconds"]))

    daily: dict[date, float] = {}
    missing: list[MissingActivity] = []
    for act in activities.iter_rows(named=True):
        day: date = act["day"]
        samples = per_activity.get(act["activity_id"])
        phys = physiology_on(config, day)
        reason = None
        if not samples:
            reason = "没有心率"
        elif phys is None:
            reason = "该日期没有生效的生理参数"
        if reason:
            missing.append(
                {
                    "activity_id": act["activity_id"],
                    "date": day.isoformat(),
                    "name": act["name"],
                    "activity_type": act["activity_type"],
                    "reason": reason,
                }
            )
            daily.setdefault(day, 0.0)
            continue
        trimp = sum(banister_trimp(s / 60, h, phys.hr_rest, phys.hr_max) for h, s in samples)
        daily[day] = daily.get(day, 0.0) + trimp
    return daily, missing


def _series(daily: dict[date, float], as_of: date) -> list[LoadPoint]:
    """CTL/ATL/TSB for every day from the first activity day to `as_of`."""
    if not daily:
        return []
    points: list[LoadPoint] = []
    ctl = atl = 0.0
    day = min(daily)
    while day <= as_of:
        load = daily.get(day, 0.0)
        tsb = ctl - atl
        ctl += (load - ctl) / CTL_DAYS
        atl += (load - atl) / ATL_DAYS
        points.append({"date": day.isoformat(), "trimp": load, "ctl": ctl, "atl": atl, "tsb": tsb})
        day += timedelta(days=1)
    return points


def _is_spike(p: LoadPoint) -> bool:
    return p["ctl"] > 0 and p["atl"] / p["ctl"] > SPIKE_RATIO


def training_load(today: date | None = None, root: Path | None = None) -> TrainingLoad:
    """The dashboard's load section as of `today` (default: the real today):
    current CTL/ATL/TSB, the last 12 weeks, the spike flag and what the
    "how is this calculated" note needs. Activities after `today` are ignored."""
    root = root or data_dir()
    as_of = today or date.today()
    config_error = None
    try:
        config = load_config(root)
    except ConfigError as err:
        config, config_error = Config(), str(err)

    result: TrainingLoad = {
        "as_of": as_of.isoformat(),
        "has_data": False,
        "current": None,
        "spike": False,
        "spike_since": None,
        "series": [],
        "missing_hr_count": 0,
        "missing_hr_recent": [],
        "config_error": config_error,
        "method": _method(physiology_on(config, as_of)),
    }
    db = open_analysis_db(root) if root.is_dir() else None
    if db is None:
        return result
    with db:
        if "activities" not in db.tables():
            return result
        daily, missing = _activity_trimp(db, config, as_of)

    points = _series(daily, as_of)
    if not points:
        return result
    window_start = (as_of - timedelta(days=SERIES_DAYS - 1)).isoformat()
    last = points[-1]
    spike_since = None
    for p in reversed(points):
        if not _is_spike(p):
            break
        spike_since = p["date"]
    result.update(
        has_data=True,
        current={
            "date": last["date"],
            "ctl": last["ctl"],
            "atl": last["atl"],
            "tsb": last["tsb"],
            "ratio": last["atl"] / last["ctl"] if last["ctl"] > 0 else None,
        },
        spike=_is_spike(last),
        spike_since=spike_since,
        series=[p for p in points if p["date"] >= window_start],
        missing_hr_count=len(missing),
        missing_hr_recent=[m for m in missing if m["date"] >= window_start],
    )
    return result
