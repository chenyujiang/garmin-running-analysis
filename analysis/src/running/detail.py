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

import heapq
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from pathlib import Path
from typing import TypedDict

import polars as pl

from running import aerobic, load, longruns
from running.aerobic import air_temperature, load_records, steady_state
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


class ActivityDetail(TypedDict):
    """GET /api/activities/{activity_id}: the header, one key per entry in
    SECTIONS, then the report."""

    activity: ActivityHeader
    summary: dict
    series: dict
    splits: dict
    route: dict | None
    route_unavailable: str | None
    metrics: dict
    report: dict  # report.Report: items and method


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


def activity_detail(activity_id: int, root: Path | None = None) -> ActivityDetail | None:
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
        detail = {"activity": header, **{key: build(d) for key, build in SECTIONS.items()}}
        # Built last: the report reads the sections above.
        return ActivityDetail(**detail, report=_report(d, detail))


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
# Time axis: seconds from the first sample, wall clock (pauses keep their
# length on the axis and are marked). The bucket width is the smallest whole
# number of seconds that keeps the total at or under MAX_POINTS once every
# pause-free stretch is bucketed on its own. With more stretches than
# MAX_POINTS the whole axis is bucketed at once and buckets may span pauses.

MAX_POINTS = 1500
# A bucket slower than this has no pace: standing still would stretch the axis.
MIN_PACE_SPEED_MPS = 0.5
NO_RECORDS = "没有逐秒记录"

# Response key -> (column in the bucket frame, reason when the column is empty).
_SERIES_COLUMNS = {
    "hr_bpm": ("heart_rate", "没有心率记录"),
    "pace_s_per_km": ("speed", "没有速度记录"),
    "gap_pace_s_per_km": ("gap_mps", "没有速度记录"),
    "altitude_m": ("altitude", "没有海拔记录"),
    "cadence_spm": ("spm", "没有步频记录"),
}
_RUNNING_SERIES = ("pace_s_per_km", "gap_pace_s_per_km", "cadence_spm")


def _bucket_width(spans: list[float], max_points: int) -> int:
    """Smallest whole seconds `w` with sum(floor(span / w) + 1) <= max_points.
    Needs len(spans) <= max_points: every span is at least one bucket."""
    w = max(1, int(sum(spans) // max_points))
    while sum(int(span // w) + 1 for span in spans) > max_points:
        w += 1
    return w


def _flag_intervals(df: pl.DataFrame, flag: str) -> list[list[float]]:
    """`[start_s, end_s]` for each run of consecutive `flag` samples. A sample
    owns the `dt_s` seconds ending at it; a pause always ends a run."""
    key = ((pl.col(flag) != pl.col(flag).shift(1)).fill_null(True) | pl.col("_pause")).cum_sum()
    runs = (
        df.with_columns(key.alias("_run"))
        .filter(pl.col(flag))
        .group_by("_run")
        .agg((pl.col("t") - pl.col("dt_s")).first().alias("a"), pl.col("t").last().alias("b"))
        .sort("a")
    )
    return [[a, b] for a, b in runs.select("a", "b").iter_rows()]


def _pace(speed: pl.Expr) -> pl.Expr:
    return pl.when(speed >= MIN_PACE_SPEED_MPS).then(1000.0 / speed).otherwise(None)


def _series(d: DetailInputs) -> dict:
    rw = d.config.run_walk
    unavailable: dict[str, str] = {}
    out: dict = {"duration_s": 0.0, "bucket_s": None, "t_s": []}
    out.update({key: [] for key in _SERIES_COLUMNS})
    intervals: dict = {"pause": [], "walking": [], "steady": []}

    recs = d.records
    if recs.is_empty():
        unavailable.update({key: NO_RECORDS for key in (*_SERIES_COLUMNS, "walking", "steady")})
    else:
        df = steady_state(recs, d.config.aerobic, rw)
        t0 = df["ts"].min()
        df = df.with_columns(((pl.col("ts") - t0).dt.total_seconds(fractional=True)).alias("t"))
        df = df.with_columns((pl.col("t").diff().fill_null(0.0) > rw.pause_gap_s).alias("_pause"))
        df = df.with_columns(pl.col("_pause").cum_sum().alias("_seg"))
        df = df.with_columns((pl.col("t") - pl.col("t").min().over("_seg")).alias("_in_seg"))
        spans = df.group_by("_seg").agg(pl.col("_in_seg").max())["_in_seg"].to_list()
        if len(spans) > MAX_POINTS:
            # More pause-free stretches than points: bucket the whole axis,
            # so a bucket may span a pause.
            df = df.with_columns(pl.lit(0).alias("_seg"), pl.col("t").alias("_in_seg"))
            spans = [float(df["t"].max())]
        w = _bucket_width(spans, MAX_POINTS)
        buckets = (
            df.with_columns((pl.col("_in_seg") // w).alias("_bucket"))
            .group_by("_seg", "_bucket")
            .agg(pl.col("t", "heart_rate", "speed", "gap_mps", "altitude", "spm").mean())
            .sort("t")
            .with_columns(
                _pace(pl.col("speed")).alias("speed"), _pace(pl.col("gap_mps")).alias("gap_mps")
            )
        )
        out["duration_s"] = float(df["t"].max())
        out["bucket_s"] = w
        out["t_s"] = buckets["t"].round(1).to_list()
        for key, (col, reason) in _SERIES_COLUMNS.items():
            if df[col].is_null().all():
                unavailable[key] = reason
            else:
                out[key] = buckets[col].round(1).to_list()

        paused = df.with_columns(pl.col("t").shift(1).alias("_prev")).filter(pl.col("_pause"))
        intervals["pause"] = [[a, b] for a, b in paused.select("_prev", "t").iter_rows()]
        if df["spm"].is_null().all():
            unavailable["walking"] = "没有步频记录"
        else:
            intervals["walking"] = _flag_intervals(
                df.with_columns((~pl.col("running")).alias("_walking")), "_walking"
            )
        if df["heart_rate"].is_null().all():
            unavailable["steady"] = "没有心率记录"
        else:
            intervals["steady"] = _flag_intervals(df, "steady")

    if not d.is_running:
        for key in (*_RUNNING_SERIES, "walking", "steady"):
            out.pop(key, None)
            intervals.pop(key, None)
            unavailable[key] = RUNNING_ONLY
        out.update({key: None for key in _RUNNING_SERIES})
        intervals.update(walking=None, steady=None)

    return {
        **out,
        "intervals": intervals,
        "unavailable": unavailable,
        "method": _series_method(d.config),
    }


def _series_method(config: Config) -> Method:
    a, rw = config.aerobic, config.run_walk
    return {
        "name": "逐秒曲线",
        "description": (
            f"横轴是从第一个采样起的秒数，暂停照实占位。降采样到最多 {MAX_POINTS} 个点："
            "按时间等分成整秒宽的桶，桶内取算术平均；每段不含暂停的时间各自分桶，"
            f"桶不跨暂停（采样间隔超过 {rw.pause_gap_s} 秒算暂停）；"
            f"不含暂停的段多于 {MAX_POINTS} 段时整条时间轴一起分桶，桶可以跨暂停。"
            "配速 = 1000 / 桶内平均速度，速度低于 "
            f"{MIN_PACE_SPEED_MPS:g} m/s 的桶不画配速。"
            f"GAP 配速用 Minetti 2002 的坡度能耗把 {a.smoothing_s} 秒平滑速度换成平地等效速度，"
            f"坡度取最近 {a.grade_window_s} 秒的海拔差 / 距离，限幅 ±{a.max_grade:g}；"
            "没有海拔时坡度按 0，和长距离表一致。"
            "走路段是跑走分类判为走的秒；稳态段和有氧能力、长距离表的稳态口径相同："
            f"去掉开头 {a.warmup_s // 60} 分钟，"
            f"平滑心率在 {a.reference_hr} ± {a.hr_band_bpm:g} bpm 内，"
            f"{a.speed_window_s} 秒内速度变化 ≤ {a.max_speed_change:.0%}。"
            "非跑步类活动只给心率和海拔。"
        ),
        "params": {
            "max_points": MAX_POINTS,
            "min_pace_speed_mps": MIN_PACE_SPEED_MPS,
            "pause_gap_s": rw.pause_gap_s,
            "smoothing_s": a.smoothing_s,
            "grade_window_s": a.grade_window_s,
            "max_grade": a.max_grade,
            "warmup_s": a.warmup_s,
            "reference_hr": a.reference_hr,
            "hr_band_bpm": a.hr_band_bpm,
        },
    }


# --- splits: laps and kilometres (ticket 04) ---------------------------------

SPLIT_M = 1000.0
MIN_LAST_SPLIT_M = 10.0  # a shorter remainder after the last full km is dropped


def _splits(d: DetailInputs) -> dict:
    unavailable: dict[str, str] = {}
    laps = _laps(d)
    if not laps:
        unavailable["laps"] = "手表没有记录圈"
    kilometres = None
    if not d.is_running:
        unavailable["kilometres"] = RUNNING_ONLY
    else:
        kilometres = _kilometres(d)
        if kilometres is None:
            unavailable["kilometres"] = "没有逐秒距离记录"
    return {
        "laps": laps,
        "kilometres": kilometres,
        "unavailable": unavailable,
        "method": _splits_method(d.config),
    }


def _laps(d: DetailInputs) -> list[dict]:
    """The watch laps as recorded. Pace and spm only for running activities:
    a cycling cadence is rpm, and doubling it is not spm."""
    if "laps" not in d.db.tables():
        return []
    rows = d.db.query(
        "SELECT * FROM a.laps WHERE activity_id = ? ORDER BY lap_index", [d.activity_id]
    ).to_dicts()
    out = []
    for r in rows:
        duration = (
            r["timer_duration_s"] if r["timer_duration_s"] is not None else r["elapsed_duration_s"]
        )
        speed = r["avg_speed_mps"]
        if speed is None and duration and r["distance_m"]:
            speed = r["distance_m"] / duration
        cadence = r["avg_cadence"]
        out.append(
            {
                "lap": r["lap_index"] + 1,
                "distance_m": r["distance_m"],
                "duration_s": duration,
                "pace_s_per_km": 1000.0 / speed if d.is_running and speed else None,
                "avg_hr_bpm": r["avg_hr_bpm"],
                "max_hr_bpm": r["max_hr_bpm"],
                "avg_cadence_spm": 2 * cadence if d.is_running and cadence is not None else None,
                "elevation_gain_m": r["elevation_gain_m"],
                "elevation_loss_m": r["elevation_loss_m"],
            }
        )
    return out


def _kilometres(d: DetailInputs) -> list[dict] | None:
    """Per-kilometre splits on `records.distance`, or None without distances.
    A sample owns the interval ending at it and goes to the kilometre that
    interval starts in."""
    recs = load_records(d.db, [d.activity_id]).filter(pl.col("distance").is_not_null())
    if recs.is_empty():
        return None
    df = steady_state(recs, d.config.aerobic, d.config.run_walk)
    total = float(df["distance"].max())
    df = df.with_columns(
        ((pl.col("distance") - pl.col("dd_m")).clip(lower_bound=0.0) // SPLIT_M)
        .cast(pl.Int64)
        .alias("_km"),
        pl.col("altitude").diff().alias("_dalt"),
    )
    full = int(total // SPLIT_M)
    last = total - full * SPLIT_M
    count = full + (1 if last >= MIN_LAST_SPLIT_M else 0)
    out = []
    for k in range(count):
        part = df.filter(pl.col("_km") == k)
        run = part.filter(pl.col("running") & (pl.col("dt_s") > 0))
        run_s = float(run["dt_s"].sum())
        run_m = float(run["dd_m"].sum())
        gap_m = float((run["gap_mps"] * run["dt_s"]).sum())
        dalt = part["_dalt"].drop_nulls()
        partial = k == full
        out.append(
            {
                "km": k + 1,
                "distance_m": last if partial else SPLIT_M,
                "partial": partial,
                "duration_s": float(part["dt_s"].sum()),
                "running_pace_s_per_km": 1000.0 * run_s / run_m if run_m > 0 else None,
                "gap_pace_s_per_km": 1000.0 * run_s / gap_m if gap_m > 0 else None,
                "avg_hr_bpm": _weighted_mean(part, "heart_rate"),
                "avg_cadence_spm": _weighted_mean(run, "spm"),
                "elevation_gain_m": float(dalt.clip(lower_bound=0).sum())
                if not dalt.is_empty()
                else None,
                "elevation_loss_m": float(-dalt.clip(upper_bound=0).sum())
                if not dalt.is_empty()
                else None,
            }
        )
    return out


def _splits_method(config: Config) -> Method:
    rw, ae = config.run_walk, config.aerobic
    return {
        "name": "分段",
        "description": (
            "圈取手表记录的圈：时长用计时时长（不含暂停），配速取圈的平均速度，"
            "步频为圈的平均单脚步频 ×2（spm）；非跑步类活动的圈不给配速和步频。"
            f"每公里分段按逐秒记录的累计距离切，每满 {SPLIT_M:g} m 一段，"
            f"最后不足 1 km 的部分单独列出并标明距离（短于 {MIN_LAST_SPLIT_M:g} m 的不列）。"
            f"跑步配速只算跑的秒（步频平滑后 ≥ {rw.cadence_spm:g} spm）；"
            f"GAP 配速用 {ae.grade_window_s} 秒坡度和 Minetti 能耗曲线把跑的秒换算成平路速度。"
            "平均心率按时间加权（暂停不计），平均步频只算跑的秒；"
            "海拔升降是逐秒海拔变化的正负分别求和。非跑步类活动没有每公里分段。"
        ),
        "params": {
            "split_m": SPLIT_M,
            "min_last_split_m": MIN_LAST_SPLIT_M,
            "cadence_spm": rw.cadence_spm,
            "grade_window_s": ae.grade_window_s,
            "max_grade": ae.max_grade,
        },
    }


# --- route shape (ticket 05) -------------------------------------------------
# Privacy: only the normalised shape and a scale leave this block. No latitude,
# longitude or centre point is returned, logged or put in `method`.

ROUTE_MAX_POINTS = 500
ROUTE_TOLERANCE_M = 0.5  # points this close to the chord add nothing visible
EARTH_RADIUS_M = 6_371_008.8  # mean radius (IUGG)
NO_GPS = "没有 GPS 记录（跑步机或室内活动）"
NO_EXTENT = "GPS 定位点不足，画不出形状"


def _route_fixes(d: DetailInputs) -> list[tuple[float, float]]:
    """(lat, lon) of the seconds with a GPS fix, in time order. Stays in this block."""
    fixes = d.db.query(
        "SELECT lat, lon FROM a.records WHERE activity_id = ?"
        " AND lat IS NOT NULL AND lon IS NOT NULL ORDER BY timestamp",
        [d.activity_id],
    )
    return list(zip(fixes["lat"], fixes["lon"], strict=True))


def _route(d: DetailInputs) -> dict | None:
    """The normalised route shape, or None (see `_route_unavailable` for why)."""
    points = _project(_route_fixes(d))
    if points is None:
        return None
    kept = _simplify(points, ROUTE_MAX_POINTS, ROUTE_TOLERANCE_M)
    xs = [points[i][0] for i in kept]
    ys = [points[i][1] for i in kept]
    x0, y_north = min(xs), max(ys)
    span = max(max(xs) - x0, y_north - min(ys))
    return {
        "x": [(x - x0) / span for x in xs],
        "y": [(y_north - y) / span for y in ys],  # screen order: y grows southwards
        "start_index": 0,
        "finish_index": len(kept) - 1,
        "metres_per_unit": span,
        "method": _route_method(),
    }


def _route_unavailable(d: DetailInputs) -> str | None:
    """Why `route` is null, or None when there is a route."""
    fixes = _route_fixes(d)
    if not fixes:
        return NO_GPS
    return NO_EXTENT if _project(fixes) is None else None


def _project(fixes: list[tuple[float, float]]) -> list[tuple[float, float]] | None:
    """Equirectangular projection to metres east and north of the bounding-box
    centre; None when the fixes don't span any distance."""
    if len(fixes) < 2:
        return None
    lats = [lat for lat, _ in fixes]
    lons = [lon for _, lon in fixes]
    lat0 = (min(lats) + max(lats)) / 2
    lon0 = (min(lons) + max(lons)) / 2
    if max(lons) == min(lons) and max(lats) == min(lats):
        return None
    k = math.radians(1) * EARTH_RADIUS_M
    kx = k * math.cos(math.radians(lat0))
    return [((lon - lon0) * kx, (lat - lat0) * k) for lat, lon in fixes]


def _simplify(points: list[tuple[float, float]], max_points: int, tolerance_m: float) -> list[int]:
    """Douglas–Peucker, capped at `max_points`: start from the two ends and
    keep splitting the segment whose farthest point is farthest from its chord
    until `max_points` are kept or every remaining point is within
    `tolerance_m` of its chord.
    Returns the kept indices in order."""
    last = len(points) - 1
    kept = {0, last}
    heap: list[tuple[float, int, int, int]] = []

    def push(i: int, j: int) -> None:
        if j - i < 2:
            return
        k, dist = max(
            ((m, _chord_distance(points[m], points[i], points[j])) for m in range(i + 1, j)),
            key=lambda t: t[1],
        )
        if dist > tolerance_m:
            heapq.heappush(heap, (-dist, k, i, j))

    push(0, last)
    while heap and len(kept) < max_points:
        _, k, i, j = heapq.heappop(heap)
        kept.add(k)
        push(i, k)
        push(k, j)
    return sorted(kept)


def _chord_distance(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]):
    """Distance from `p` to the segment `a`–`b` (to `a` when they coincide, as
    at the ends of a loop)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _route_method() -> Method:
    return {
        "name": "路线形状",
        "description": (
            "只用有 GPS 定位的秒。按等距矩形投影换成以路线中心为原点的米制平面"
            "（东西方向乘以中心纬度的余弦），再整体缩放到 0–1，长边占满，长宽比不变；"
            f"用 Douglas–Peucker 简化到最多 {ROUTE_MAX_POINTS} 个点，"
            f"离弦不到 {ROUTE_TOLERANCE_M:g} 米的点不保留，起点和终点保留。"
            "比例尺是 0–1 的 1 个单位对应的米数。接口不返回任何经纬度或中心点，"
            "也不加载在线底图，路线位置不离开本机。"
        ),
        "params": {
            "max_points": ROUTE_MAX_POINTS,
            "tolerance_m": ROUTE_TOLERANCE_M,
            "projection": "equirectangular",
        },
    }


# --- run metrics: TRIMP, HR zones, aerobic value, EF (ticket 06) -------------
# Friel's running LTHR zones: TrainingPeaks, "Joe Friel's Quick Guide to
# Setting Zones" (2012, updated 2026): Z1 < 85 %, Z2 85-89 %, Z3 90-94 %,
# Z4 95-99 %, Z5a-c >= 100 % of LTHR. Z5a/b/c are one zone here.


def _hr_zones(d: DetailInputs, phys: load.Physiology | None) -> tuple[dict | None, str | None]:
    """Time in each zone over the seconds with a heart rate (pauses and the
    first sample weigh nothing), or None and the reason."""
    hr = d.records.filter(pl.col("heart_rate").is_not_null() & (pl.col("dt_s") > 0))
    if hr.is_empty():
        return None, "没有逐秒心率" if d.activity["avg_hr_bpm"] else load.NO_HR
    if phys is None:
        return None, load.NO_PHYSIOLOGY
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
        return None, NO_RECORDS
    if d.records["heart_rate"].is_null().all():
        return None, load.NO_HR
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
    """EF and decoupling as in the long-run table (`longruns.per_run_ef`).
    The gates are the aerobic value's (road run, `gps_usable`, enough steady
    time), so a run without an aerobic value has no EF, for the same reason."""
    if aerobic_why:
        return None, aerobic_why
    rows = longruns.per_run_ef(load_records(d.db, [d.activity_id]), d.config).to_dicts()
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


# --- report ------------------------------------------------------------------
# Not in SECTIONS: the report reads the other sections' output.


def _report(d: DetailInputs, detail: dict) -> dict:
    from running.report import report_context, run_report

    return dict(run_report(detail, report_context(d, detail)))


# --- section registry --------------------------------------------------------
# One entry per section, in page order.

SECTIONS: dict[str, Section] = {
    "summary": _summary,
    "series": _series,
    "splits": _splits,
    "route": _route,
    "route_unavailable": _route_unavailable,
    "metrics": _metrics,
}
