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


# --- section registry --------------------------------------------------------
# One entry per section, in page order. Each ticket adds its own line in its
# own slot; the comment lines between the slots keep parallel edits apart.

SECTIONS: dict[str, Section] = {
    "summary": _summary,
    # series (ticket 03)
    # splits (ticket 04)
    # route (ticket 05)
    "route": _route,
    "route_unavailable": _route_unavailable,
    # metrics (ticket 06)
}
