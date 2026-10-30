"""Training load: per-second Banister TRIMP, CTL/ATL/TSB.

Formula sources and the choice of recursion are recorded in
`.scratch/running-tool/issues/09-training-load.md`.

- TRIMP per activity = Σ Δt[min] · x · 0.64 · e^(1.92·x) over records with a
  heart rate, x = (HR − HRrest) / (HRmax − HRrest) clamped to [0, 1], using
  the physiology set in effect on the activity's local start date. Δt is the
  gap to the next record, capped at `[load] max_sample_gap_s` (default 10 s;
  pauses do not count); the last record counts 1 s.
- Activities without heart-rate records but with an average HR in the Garmin
  summary (`activities.avg_hr_bpm`): TRIMP = duration_s/60 · x · 0.64 ·
  e^(1.92·x) with x from that average (Banister's original mean-HR form; it
  comes out lower than the per-second sum for uneven efforts). They are
  reported as `summary_hr_*`. Activities with neither are missing and add
  nothing to the daily load.
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

from running.config import Config, Physiology
from running.db import AnalysisDb, open_analysis_db
from running.section import Method, section_inputs

# Banister TRIMP, male coefficients (Banister & Calvert 1980; b from Morton,
# Fitz-Clarke & Banister 1990).
TRIMP_A = 0.64
TRIMP_B = 1.92
CTL_DAYS = 42
ATL_DAYS = 7
SPIKE_RATIO = 1.5
SERIES_DAYS = 84  # 12 weeks


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


class LoadActivity(TypedDict):
    activity_id: int
    date: str
    name: str | None
    activity_type: str
    reason: str


class LoadCurrent(TypedDict):
    date: str
    ctl: float
    atl: float
    tsb: float
    ratio: float | None


class TrainingLoad(TypedDict):
    today: str
    has_data: bool
    current: LoadCurrent | None
    spike: bool
    spike_since: str | None
    series: list[LoadPoint]
    missing_hr_count: int
    missing_hr_recent: list[LoadActivity]
    summary_hr_count: int  # TRIMP estimated from the summary's average HR
    summary_hr_recent: list[LoadActivity]
    config_error: str | None
    method: Method


def _method(phys: Physiology | None, max_gap_s: float) -> Method:
    current = (
        f"当前参数：HRrest {phys.hr_rest}、HRmax {phys.hr_max}"
        f"（{phys.effective_from.isoformat()} 起生效）。"
        if phys
        else "config.toml 里没有当前生效的生理参数。"
    )
    return {
        "name": "Banister TRIMP（逐秒，男性系数）",
        "description": (
            "TRIMP = Σ Δt[min] · x · 0.64 · e^(1.92·x)，x = (HR − HRrest) / (HRmax − HRrest)，"
            f"截断在 0 到 1。{current}每个活动用它当天生效的那组参数。"
            f"相邻两个心率样本的间隔超过 {max_gap_s:g} 秒时（暂停）只按 {max_gap_s:g} 秒算。"
            "所有带心率的活动都计入：没有逐秒心率、但 Garmin 摘要里有平均心率的活动，"
            "用平均心率和总时长按同一公式估算（起伏大的课会比逐秒累加偏低）；"
            "两者都没有的记为缺失，不计入。"
            f"CTL 是 {CTL_DAYS} 天、ATL 是 {ATL_DAYS} 天的指数加权平均，递推用 1/N 形式："
            "今天 = 昨天 + (当天 TRIMP − 昨天) / N。TSB = 昨天的 CTL − 昨天的 ATL。"
            f"ATL/CTL 超过 {SPIKE_RATIO:g} 时提示负荷突增。数值只作相对比较。"
        ),
        "params": {
            "trimp_a": TRIMP_A,
            "trimp_b": TRIMP_B,
            "hr_rest": phys.hr_rest if phys else None,
            "hr_max": phys.hr_max if phys else None,
            "physiology_effective_from": phys.effective_from.isoformat() if phys else None,
            "max_sample_gap_s": max_gap_s,
            "summary_hr_fallback": "duration_s x avg_hr_bpm",
            "ctl_days": CTL_DAYS,
            "atl_days": ATL_DAYS,
            "recursion": "1/N",
            "spike_ratio": SPIKE_RATIO,
        },
    }


# The cap on Δt is the single query parameter.
_HR_SECONDS_SQL = """
WITH r AS (
    SELECT activity_id, heart_rate,
           epoch(CAST(rtrim(timestamp, 'Z') AS TIMESTAMP)) AS t
    FROM a.records
), d AS (
    SELECT activity_id, heart_rate,
           least(greatest(coalesce(
               lead(t) OVER (PARTITION BY activity_id ORDER BY t) - t, 1.0), 0.0),
               ?) AS dt
    FROM r
)
SELECT activity_id, heart_rate AS hr, sum(dt) AS seconds
FROM d WHERE heart_rate IS NOT NULL AND heart_rate > 0
GROUP BY activity_id, heart_rate
"""


def _activity_trimp(
    db: AnalysisDb, config: Config, today: date
) -> tuple[dict[date, float], list[LoadActivity], list[LoadActivity]]:
    """Daily TRIMP up to `today`, activities with missing TRIMP, and
    activities whose TRIMP comes from the summary's average HR."""
    activities = db.query(
        "SELECT activity_id, activity_type, activity_name AS name, avg_hr_bpm, duration_s,"
        " CAST(substr(start_time_local, 1, 10) AS DATE) AS day FROM a.activities"
        " WHERE CAST(substr(start_time_local, 1, 10) AS DATE) <= ? ORDER BY start_time_local",
        [today],
    )
    hr = (
        db.query(_HR_SECONDS_SQL, [config.load.max_sample_gap_s])
        if "records" in db.tables()
        else pl.DataFrame()
    )
    per_activity: dict[int, list[tuple[float, float]]] = {}
    for row in hr.iter_rows(named=True):
        per_activity.setdefault(row["activity_id"], []).append((row["hr"], row["seconds"]))

    daily: dict[date, float] = {}
    missing: list[LoadActivity] = []
    from_summary: list[LoadActivity] = []
    for act in activities.iter_rows(named=True):
        day: date = act["day"]
        samples = per_activity.get(act["activity_id"])
        avg_hr, duration = act["avg_hr_bpm"], act["duration_s"]
        has_summary_hr = bool(avg_hr and avg_hr > 0 and duration and duration > 0)
        phys = physiology_on(config, day)

        def entry(reason: str, act: dict = act, day: date = day) -> LoadActivity:
            return {
                "activity_id": act["activity_id"],
                "date": day.isoformat(),
                "name": act["name"],
                "activity_type": act["activity_type"],
                "reason": reason,
            }

        if not samples and not has_summary_hr:
            missing.append(entry("没有心率"))
        elif phys is None:
            missing.append(entry("该日期没有生效的生理参数"))
        elif samples:
            trimp = sum(banister_trimp(s / 60, h, phys.hr_rest, phys.hr_max) for h, s in samples)
            daily[day] = daily.get(day, 0.0) + trimp
            continue
        else:
            trimp = banister_trimp(duration / 60, avg_hr, phys.hr_rest, phys.hr_max)
            daily[day] = daily.get(day, 0.0) + trimp
            from_summary.append(entry("没有逐秒心率，按摘要的平均心率估算"))
            continue
        daily.setdefault(day, 0.0)
    return daily, missing, from_summary


def _series(daily: dict[date, float], today: date) -> list[LoadPoint]:
    """CTL/ATL/TSB for every day from the first activity day to `today`."""
    if not daily:
        return []
    points: list[LoadPoint] = []
    ctl = atl = 0.0
    day = min(daily)
    while day <= today:
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
    inputs = section_inputs(today, root)
    today, config = inputs.today, inputs.config
    result: TrainingLoad = {
        "today": today.isoformat(),
        "has_data": False,
        "current": None,
        "spike": False,
        "spike_since": None,
        "series": [],
        "missing_hr_count": 0,
        "missing_hr_recent": [],
        "summary_hr_count": 0,
        "summary_hr_recent": [],
        "config_error": inputs.config_error,
        "method": _method(physiology_on(config, today), config.load.max_sample_gap_s),
    }
    db = open_analysis_db(inputs.root)
    if db is None:
        return result
    with db:
        if "activities" not in db.tables():
            return result
        daily, missing, from_summary = _activity_trimp(db, config, today)

    points = _series(daily, today)
    if not points:
        return result
    window_start = (today - timedelta(days=SERIES_DAYS - 1)).isoformat()
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
        summary_hr_count=len(from_summary),
        summary_hr_recent=[m for m in from_summary if m["date"] >= window_start],
    )
    return result
