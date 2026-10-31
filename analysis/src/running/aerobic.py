"""Aerobic capacity: grade-adjusted speed (GAP) at the reference heart rate.

Per run (spec, "有氧能力"):

1. Outdoor road runs only (`AEROBIC_TYPES`): no treadmill, no trail. The
   per-second records must also have position and altitude (a road run logged
   on a treadmill has neither), and at most `max_fast_s` samples above
   `max_speed_mps` (GPS drift). See `gps_usable`.
2. Each second is classified run/walk (`running.runwalk.classify_records`).
3. HR, speed and barometric altitude get a trailing `smoothing_s` mean.
4. Grade = rise of the smoothed altitude / distance over the last
   `grade_window_s` seconds, clipped to +-`max_grade`; GAP speed =
   smoothed speed x Cr(grade) / Cr(0) (Minetti 2002).
5. Steady seconds: past the first `warmup_s` of moving time, running, not the
   first sample after a pause, smoothed HR within `reference_hr` +- `hr_band_bpm`,
   smoothed speed varying by at most `max_speed_change` over `speed_window_s`,
   and |HR - spm| >= `min_hr_spm_gap` (an optical sensor locked on cadence).
6. Runs with less than `min_steady_s` of steady time are left out.
7. Least-squares line GAP ~ HR over the steady seconds, read at `reference_hr`.
   When HR barely varies (variance < 1 bpm^2) the line is undefined and the
   mean GAP speed is used.

Per week (Monday start, by `start_time_local`): median of the valid runs, empty
when fewer than `min_runs_per_week`; the rolling median covers the non-empty
weekly medians of the last `rolling_weeks` weeks and is empty in empty weeks
(no interpolation). Air temperature comes from the Open-Meteo hourly table
(`air_temperature`); the week's is the median of its valid runs, and a week at
or above `hot_week_c` is `hot`. Display only: the GAP value is not corrected.
"""

from datetime import date, timedelta
from pathlib import Path
from typing import Literal, TypedDict

import polars as pl

from running.config import Aerobic, Config, RunWalk
from running.db import AnalysisDb, open_analysis_db
from running.runwalk import classify_records
from running.section import Method, section_inputs

# Minetti et al. 2002, J Appl Physiol 93:1039-1046, Fig. 1: energy cost of
# running in J/kg/m against gradient i (rise over horizontal run), R^2 = 0.999.
_CR_COEFFS = (155.4, -30.4, -43.3, 46.3, 19.5, 3.6)  # i^5 .. i^0

# Garmin activity type keys for outdoor road running.
AEROBIC_TYPES: frozenset[str] = frozenset({"running", "street_running"})

Range = Literal["6m", "1y", "2y", "all"]
RANGE_WEEKS: dict[str, int] = {"6m": 26, "1y": 52, "2y": 104}

_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_MIN_HR_VARIANCE = 1.0
# A run gets air temperature from a grid point at most 0.2° away in latitude
# and in longitude (positions and grid points both in whole tenths).
_GRID_REACH_TENTHS = 2


def minetti_cr(grade: float) -> float:
    """Energy cost of running Cr(i) in J/kg/m at gradient `grade` (tan, not degrees)."""
    value = 0.0
    for c in _CR_COEFFS:
        value = value * grade + c
    return value


CR_FLAT = minetti_cr(0.0)  # 3.6


def gap_speed(speed_mps: float, grade: float) -> float:
    """Flat-ground speed with the same metabolic power: v x Cr(i) / Cr(0)."""
    return speed_mps * minetti_cr(grade) / CR_FLAT


def _cr_expr(grade: pl.Expr) -> pl.Expr:
    value = pl.lit(0.0)
    for c in _CR_COEFFS:
        value = value * grade + c
    return value


def load_records(db: AnalysisDb, activity_ids: list[int]) -> pl.DataFrame:
    """Per-second records for the activities, with `ts` parsed (UTC, naive)."""
    schema = {
        "activity_id": pl.Int64,
        "ts": pl.Datetime("us"),
        "heart_rate": pl.Float64,
        "speed": pl.Float64,
        "cadence": pl.Float64,
        "altitude": pl.Float64,
        "distance": pl.Float64,
    }
    if not activity_ids or "records" not in db.tables():
        return pl.DataFrame(schema=schema)
    id_list = ", ".join("?" for _ in activity_ids)
    df = db.query(
        "SELECT activity_id, strptime(timestamp, ?) AS ts, heart_rate, speed, cadence,"
        " altitude, distance"
        f" FROM a.records WHERE activity_id IN ({id_list})",
        [_TS_FORMAT, *activity_ids],
    )
    if df.is_empty():
        return pl.DataFrame(schema=schema)
    return df.cast(schema)


def gps_usable(db: AnalysisDb, activity_ids: list[int], aerobic: Aerobic) -> set[int]:
    """The activities whose per-second records are good enough for GAP: at
    least one sample with lat, lon and altitude each (no treadmill-like run),
    and at most `max_fast_s` samples faster than `max_speed_mps` (no GPS drift).
    Shared by the aerobic metric and the long-run EF/decoupling."""
    if not activity_ids or "records" not in db.tables():
        return set()
    id_list = ", ".join("?" for _ in activity_ids)
    df = db.query(
        "SELECT activity_id FROM a.records"
        f" WHERE activity_id IN ({id_list}) GROUP BY activity_id"
        " HAVING count(lat) > 0 AND count(lon) > 0 AND count(altitude) > 0"
        " AND count(*) FILTER (WHERE speed > ?) <= ?",
        [*activity_ids, aerobic.max_speed_mps, aerobic.max_fast_s],
    )
    return set(df["activity_id"].to_list()) if not df.is_empty() else set()


_AIR_SCHEMA = {"activity_id": pl.Int64, "temperature_c": pl.Float64}


def air_temperature(db: AnalysisDb, activity_ids: list[int]) -> pl.DataFrame:
    """Air temperature at each run's midpoint from `hourly_weather` (Open-Meteo,
    importer migration 7): columns activity_id, temperature_c, one row per
    activity that gets a value.

    Midpoint = start_time_utc + half the elapsed duration (`duration_s` when
    that is missing); linear interpolation between the whole hours before and
    after it, which must both have a value and be at most an hour apart. The
    run's position is the median lat and lon of its records, each rounded to
    0.1°; it takes the nearest grid point and only when both differences are
    at most `_GRID_REACH_TENTHS` tenths of a degree. Empty without the table."""
    empty = pl.DataFrame(schema=_AIR_SCHEMA)
    if not activity_ids or not {"hourly_weather", "records", "activities"} <= db.tables():
        return empty
    # Grid points and positions in whole tenths of a degree, so they compare exactly.
    grids = db.query(
        "SELECT DISTINCT CAST(round(grid_lat * 10) AS BIGINT) AS g_lat,"
        " CAST(round(grid_lon * 10) AS BIGINT) AS g_lon FROM a.hourly_weather"
    )
    if grids.is_empty():
        return empty
    id_list = ", ".join("?" for _ in activity_ids)
    runs = db.query(
        "SELECT activity_id,"
        " CAST(round(round(median(lat), 1) * 10) AS BIGINT) AS p_lat,"
        " CAST(round(round(median(lon), 1) * 10) AS BIGINT) AS p_lon"
        f" FROM a.records WHERE activity_id IN ({id_list})"
        " GROUP BY activity_id HAVING count(lat) > 0 AND count(lon) > 0",
        list(activity_ids),
    )
    if runs.is_empty():
        return empty
    dist = (pl.col("p_lat") - pl.col("g_lat")) ** 2 + (pl.col("p_lon") - pl.col("g_lon")) ** 2
    reach = _GRID_REACH_TENTHS
    near = (
        runs.join(grids, how="cross")
        .sort("activity_id", dist, "g_lat", "g_lon")
        .group_by("activity_id", maintain_order=True)
        .first()
        .filter(
            ((pl.col("p_lat") - pl.col("g_lat")).abs() <= reach)
            & ((pl.col("p_lon") - pl.col("g_lon")).abs() <= reach)
        )
    )
    if near.is_empty():
        return empty
    acts = db.query(
        "SELECT activity_id, strptime(start_time_utc, ?) AS start_utc,"
        " coalesce(elapsed_duration_s, duration_s) AS elapsed_s"
        f" FROM a.activities WHERE activity_id IN ({id_list})",
        [_TS_FORMAT, *activity_ids],
    )
    mid = (
        near.join(acts, on="activity_id")
        .drop_nulls("elapsed_s")
        .with_columns(
            (
                pl.col("start_utc").cast(pl.Datetime("us"))
                + pl.duration(microseconds=(pl.col("elapsed_s") * 500_000).round().cast(pl.Int64))
            ).alias("mid")
        )
        .select("activity_id", "g_lat", "g_lon", "mid")
        .sort("mid")
    )
    hourly = (
        db.query(
            "SELECT CAST(round(grid_lat * 10) AS BIGINT) AS g_lat,"
            " CAST(round(grid_lon * 10) AS BIGINT) AS g_lon,"
            " strptime(time_utc, ?) AS t, temperature_c AS c"
            " FROM a.hourly_weather WHERE temperature_c IS NOT NULL",
            [_TS_FORMAT],
        )
        .with_columns(pl.col("t").cast(pl.Datetime("us")))
        .sort("t")
    )
    if mid.is_empty() or hourly.is_empty():
        return empty
    by = ["g_lat", "g_lon"]
    before = hourly.rename({"t": "t0", "c": "c0"})
    after = hourly.rename({"t": "t1", "c": "c1"})
    # Both sides are sorted by time; the `by` groups only split them.
    asof = {"left_on": "mid", "by": by, "check_sortedness": False}
    df = mid.join_asof(before, right_on="t0", strategy="backward", **asof).join_asof(
        after, right_on="t1", strategy="forward", **asof
    )
    span = (pl.col("t1") - pl.col("t0")).dt.total_seconds()
    frac = (pl.col("mid") - pl.col("t0")).dt.total_seconds() / span
    value = (
        pl.when(span == 0)
        .then(pl.col("c0"))
        .when(span <= 3600)
        .then(pl.col("c0") + (pl.col("c1") - pl.col("c0")) * frac)
        .otherwise(None)
    )
    return (
        df.select("activity_id", value.alias("temperature_c"))
        .drop_nulls("temperature_c")
        .cast(_AIR_SCHEMA)
    )


def steady_state(records: pl.DataFrame, aerobic: Aerobic, run_walk: RunWalk) -> pl.DataFrame:
    """Classify each second and add `hr_smooth`, `speed_smooth`, `grade`,
    `gap_mps` and `steady` (bool), plus `classify_records`' `spm`, `dt_s`,
    `dd_m`, `running`. `records` as returned by `load_records`."""
    by = "activity_id"
    smooth = f"{aerobic.smoothing_s}s"
    speed_window = f"{aerobic.speed_window_s}s"
    df = classify_records(records, run_walk)
    df = df.with_columns(
        pl.col("heart_rate").rolling_mean_by("ts", window_size=smooth).over(by).alias("hr_smooth"),
        pl.col("speed").rolling_mean_by("ts", window_size=smooth).over(by).alias("speed_smooth"),
        pl.col("altitude").rolling_mean_by("ts", window_size=smooth).over(by).alias("_alt"),
        pl.col("dt_s").cum_sum().over(by).alias("_moving_s"),
    )
    df = df.with_columns(
        pl.col("speed_smooth")
        .rolling_max_by("ts", window_size=speed_window)
        .over(by)
        .alias("_vmax"),
        pl.col("speed_smooth")
        .rolling_min_by("ts", window_size=speed_window)
        .over(by)
        .alias("_vmin"),
        pl.col("speed_smooth")
        .rolling_mean_by("ts", window_size=speed_window)
        .over(by)
        .alias("_vmean"),
    )

    # Grade over the last `grade_window_s` seconds: the sample at (or just
    # before) ts - window in the same activity.
    back = (
        df.select(
            by,
            pl.col("ts").alias("_ts_b"),
            pl.col("_alt").alias("_alt_b"),
            pl.col("distance").alias("_dist_b"),
        )
        .drop_nulls("_ts_b")
        .sort("_ts_b")
    )
    df = (
        df.with_columns((pl.col("ts") - pl.duration(seconds=aerobic.grade_window_s)).alias("_ts_q"))
        .sort("_ts_q")
        .join_asof(
            back,
            left_on="_ts_q",
            right_on="_ts_b",
            by=by,
            strategy="backward",
            check_sortedness=False,
        )
        .sort(by, "ts")
    )
    rise = pl.col("_alt") - pl.col("_alt_b")
    run_m = pl.col("distance") - pl.col("_dist_b")
    df = df.with_columns(
        pl.when(run_m >= 1.0)
        .then(rise / run_m)
        .otherwise(0.0)
        .fill_null(0.0)
        .fill_nan(0.0)
        .clip(-aerobic.max_grade, aerobic.max_grade)
        .alias("grade")
    )
    df = df.with_columns(
        (pl.col("speed_smooth") * _cr_expr(pl.col("grade")) / CR_FLAT).alias("gap_mps")
    )

    steady = (
        pl.col("running")
        # A sample owns the interval ending at it: that interval must start
        # after the warm-up.
        & (pl.col("_moving_s") - pl.col("dt_s") >= aerobic.warmup_s)
        & (pl.col("dt_s") > 0)
        & ((pl.col("hr_smooth") - aerobic.reference_hr).abs() <= aerobic.hr_band_bpm)
        & (pl.col("_vmean") > 0)
        & ((pl.col("_vmax") - pl.col("_vmin")) / pl.col("_vmean") <= aerobic.max_speed_change)
        & ((pl.col("heart_rate") - pl.col("spm")).abs() >= aerobic.min_hr_spm_gap)
    )
    df = df.with_columns(steady.fill_null(False).alias("steady"))
    return df.drop(
        "_alt", "_moving_s", "_vmax", "_vmin", "_vmean", "_ts_q", "_ts_b", "_alt_b", "_dist_b"
    )


_RUN_SCHEMA = {
    "activity_id": pl.Int64,
    "start_time_local": pl.String,
    "steady_s": pl.Float64,
    "mean_hr": pl.Float64,
    "speed_mps": pl.Float64,
    "temperature_c": pl.Float64,
    "valid": pl.Boolean,
}


def aerobic_runs(
    db: AnalysisDb,
    config: Config,
    since_local: str | None = None,
    until_local: str | None = None,
) -> pl.DataFrame:
    """One row per outdoor road run starting in [since_local, until_local)
    (wall-clock ISO strings; open-ended when None).

    Columns: activity_id, start_time_local, steady_s, mean_hr (steady seconds),
    speed_mps (GAP speed at reference HR; null when not valid), temperature_c
    (air temperature at the midpoint, see `air_temperature`), valid (enough
    steady time and `gps_usable`)."""
    aerobic = config.aerobic
    if "activities" not in db.tables():
        return pl.DataFrame(schema=_RUN_SCHEMA)
    types = sorted(AEROBIC_TYPES)
    where = f"activity_type IN ({', '.join('?' for _ in types)})"
    params: list = list(types)
    if since_local is not None:
        where += " AND start_time_local >= ?"
        params.append(since_local)
    if until_local is not None:
        where += " AND start_time_local < ?"
        params.append(until_local)
    acts = db.query(f"SELECT activity_id, start_time_local FROM a.activities WHERE {where}", params)
    if acts.is_empty():
        return pl.DataFrame(schema=_RUN_SCHEMA)
    recs = load_records(db, acts["activity_id"].to_list())
    if recs.is_empty():
        per_run = pl.DataFrame(
            schema={
                k: _RUN_SCHEMA[k]
                for k in _RUN_SCHEMA
                if k not in ("start_time_local", "temperature_c")
            }
        )
    else:
        df = steady_state(recs, aerobic, config.run_walk)
        hr = pl.col("hr_smooth").filter(pl.col("steady"))
        gap = pl.col("gap_mps").filter(pl.col("steady"))
        per_run = df.group_by("activity_id").agg(
            pl.col("dt_s").filter(pl.col("steady")).sum().alias("steady_s"),
            hr.mean().alias("mean_hr"),
            gap.mean().alias("_mean_gap"),
            hr.var(ddof=0).alias("_var_hr"),
            pl.cov(hr, gap, ddof=0).alias("_cov"),
        )
        slope = (
            pl.when(pl.col("_var_hr") >= _MIN_HR_VARIANCE)
            .then(pl.col("_cov") / pl.col("_var_hr"))
            .otherwise(0.0)
        )
        usable = gps_usable(db, acts["activity_id"].to_list(), aerobic)
        valid = (pl.col("steady_s") >= aerobic.min_steady_s) & pl.col("activity_id").is_in(
            sorted(usable)
        )
        per_run = per_run.with_columns(
            valid.fill_null(False).alias("valid"),
            pl.when(valid)
            .then(pl.col("_mean_gap") + slope * (aerobic.reference_hr - pl.col("mean_hr")))
            .otherwise(None)
            .alias("speed_mps"),
        )
    air = air_temperature(db, acts["activity_id"].to_list())
    out = (
        acts.join(per_run, on="activity_id", how="left").join(air, on="activity_id", how="left")
    ).with_columns(pl.col("valid").fill_null(False), pl.col("steady_s").fill_null(0.0))
    return out.select(_RUN_SCHEMA.keys()).cast(_RUN_SCHEMA).sort("start_time_local")


class AerobicWeek(TypedDict):
    week_start: str  # Monday, YYYY-MM-DD
    runs: int  # valid runs
    speed_mps: float | None  # weekly median GAP speed at reference HR
    pace_s_per_km: float | None
    rolling_speed_mps: float | None
    rolling_pace_s_per_km: float | None
    temperature_c: float | None  # median air temperature of the week's valid runs
    hot: bool  # temperature_c >= hot_week_c
    complete: bool  # False for the current week


class AerobicRun(TypedDict):
    activity_id: int
    start_time_local: str
    steady_s: float
    mean_hr: float | None
    speed_mps: float
    pace_s_per_km: float
    temperature_c: float | None


class AerobicTrend(TypedDict):
    today: str
    range: str
    has_data: bool
    weeks: list[AerobicWeek]  # oldest first, the last one is this week
    runs: list[AerobicRun]  # valid runs in the range, newest first
    method: Method


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _pace(speed: float | None) -> float | None:
    return 1000.0 / speed if speed else None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(pl.Series(values).median())


def aerobic_trend(
    range_: Range = "1y", today: date | None = None, root: Path | None = None
) -> AerobicTrend:
    inputs = section_inputs(today, root)
    today, config = inputs.today, inputs.config
    aerobic = config.aerobic
    this_monday = _week_start(today)
    until = (today + timedelta(days=1)).isoformat()

    db = open_analysis_db(inputs.root)
    runs = pl.DataFrame(schema=_RUN_SCHEMA)
    first_monday = this_monday
    if range_ in RANGE_WEEKS:
        first_monday = this_monday - timedelta(weeks=RANGE_WEEKS[range_] - 1)
    lead = timedelta(weeks=aerobic.rolling_weeks - 1)
    if db is not None:
        with db:
            since = None if range_ == "all" else (first_monday - lead).isoformat()
            runs = aerobic_runs(db, config, since_local=since, until_local=until)
    runs = runs.with_columns(
        pl.col("start_time_local").str.slice(0, 10).str.to_date().alias("day")
    ).with_columns(pl.col("day").dt.truncate("1w").alias("week"))
    if range_ == "all" and not runs.is_empty():
        first_monday = min(runs["week"].min(), this_monday)

    valid = runs.filter(pl.col("valid"))
    speeds: dict[date, list[float]] = {}
    for row in valid.iter_rows(named=True):
        speeds.setdefault(row["week"], []).append(row["speed_mps"])
    temps: dict[date, list[float]] = {}
    for row in valid.drop_nulls("temperature_c").iter_rows(named=True):
        temps.setdefault(row["week"], []).append(row["temperature_c"])

    def weekly_median(monday: date) -> float | None:
        values = speeds.get(monday, [])
        return _median(values) if len(values) >= aerobic.min_runs_per_week else None

    weeks: list[AerobicWeek] = []
    monday = first_monday
    while monday <= this_monday:
        median = weekly_median(monday)
        rolling = None
        if median is not None:
            window = [
                weekly_median(monday - timedelta(weeks=k)) for k in range(aerobic.rolling_weeks)
            ]
            rolling = _median([v for v in window if v is not None])
        air = _median(temps.get(monday, []))
        weeks.append(
            {
                "week_start": monday.isoformat(),
                "runs": len(speeds.get(monday, [])),
                "speed_mps": median,
                "pace_s_per_km": _pace(median),
                "rolling_speed_mps": rolling,
                "rolling_pace_s_per_km": _pace(rolling),
                "temperature_c": air,
                "hot": air is not None and air >= aerobic.hot_week_c,
                "complete": monday != this_monday,
            }
        )
        monday += timedelta(weeks=1)

    in_range = valid.filter(pl.col("week") >= first_monday).sort(
        "start_time_local", descending=True
    )
    return {
        "today": today.isoformat(),
        "range": range_,
        "has_data": not valid.is_empty(),
        "weeks": weeks,
        "runs": [
            {
                "activity_id": r["activity_id"],
                "start_time_local": r["start_time_local"],
                "steady_s": r["steady_s"],
                "mean_hr": r["mean_hr"],
                "speed_mps": r["speed_mps"],
                "pace_s_per_km": 1000.0 / r["speed_mps"],
                "temperature_c": r["temperature_c"],
            }
            for r in in_range.iter_rows(named=True)
        ],
        "method": _method(aerobic, config.run_walk),
    }


# The two `gps_usable` rules, worded for the method notes ({a} is an Aerobic).
_EXCLUSIONS = (
    "逐秒记录里没有 GPS 位置或没有海拔的跑步（实际是跑步机）不计入；"
    "逐秒速度超过 {a.max_speed_mps:g} m/s 的秒累计超过 {a.max_fast_s} 秒的跑步"
    "（GPS 漂移）不计入。这两类跑步照常计入跑量和训练负荷。"
)


def exclusions_note(a: Aerobic) -> str:
    """The `gps_usable` rules for a method description."""
    return _EXCLUSIONS.format(a=a)


def _method(a: Aerobic, rw: RunWalk) -> Method:
    return {
        "name": f"参考心率 {a.reference_hr} bpm 下的 GAP 配速",
        "description": (
            "只算户外路跑（不含跑步机和越野）。"
            f"{exclusions_note(a)}去掉前 "
            f"{a.warmup_s // 60} 分钟；心率、速度、气压海拔各做 {a.smoothing_s} 秒滚动平均。"
            f"稳态秒要同时满足：在跑（步频规则同周跑量）、平滑心率在 {a.reference_hr} ± "
            f"{a.hr_band_bpm:g} bpm 内、{a.speed_window_s} 秒内平滑速度变化 ≤ "
            f"{a.max_speed_change:.0%}、不是暂停后的第一秒、心率与 spm 相差 ≥ "
            f"{a.min_hr_spm_gap:g}（防止光电心率锁定步频）。"
            f"稳态时长不足 {a.min_steady_s // 60} 分钟的跑步不计入。"
            f"坡度 = 最近 {a.grade_window_s} 秒的海拔变化 ÷ 距离，限制在 ±{a.max_grade:.0%}；"
            "GAP 速度 = 速度 × Cr(i) ÷ Cr(0)，Cr(i) = 155.4i⁵ − 30.4i⁴ − 43.3i³ + 46.3i² "
            "+ 19.5i + 3.6（Minetti 2002）。在稳态秒上拟合 GAP 速度 ~ 心率的直线，"
            f"取 {a.reference_hr} bpm 处的值；心率几乎不变时用平均 GAP 速度。"
            f"每周取有效跑步的中位数，不足 {a.min_runs_per_week} 次的周留空、不插值；"
            f"{a.rolling_weeks} 周滚动中位数只用非空周，空周不画。"
            "气温来自 Open-Meteo 历史天气（逐小时 2 米气温，一个 0.1° 格点）："
            "每次跑步取中点（开始时间加总时长的一半）前后两个整点的气温线性插值，"
            "缺一个整点时留空；只有经纬度中位数取整到 0.1° 后离格点都不超过 0.2° 的跑步才配气温。"
            "每周气温取该周有效跑步气温的中位数。"
            f"周气温中位数 ≥ {a.hot_week_c:g} °C 的周标为高温周。"
            "不做温度校正：气温只能解释配速变化的很小一部分（R² 0.002），"
            "高温周的配速可能偏慢，只做标注。"
        ),
        "params": {
            "reference_hr": a.reference_hr,
            "warmup_s": a.warmup_s,
            "smoothing_s": a.smoothing_s,
            "hr_band_bpm": a.hr_band_bpm,
            "speed_window_s": a.speed_window_s,
            "max_speed_change": a.max_speed_change,
            "min_hr_spm_gap": a.min_hr_spm_gap,
            "min_steady_s": a.min_steady_s,
            "grade_window_s": a.grade_window_s,
            "max_grade": a.max_grade,
            "min_runs_per_week": a.min_runs_per_week,
            "rolling_weeks": a.rolling_weeks,
            "max_speed_mps": a.max_speed_mps,
            "max_fast_s": a.max_fast_s,
            "hot_week_c": a.hot_week_c,
            "cadence_spm": rw.cadence_spm,
            "activity_types": sorted(AEROBIC_TYPES),
            "week": "monday-sunday, start_time_local",
        },
    }
