"""The activity list: every activity, newest first, filtered and paged.

Spec (run-detail), "running/activities.py".

- `type_filter = "running"` keeps `RUNNING_TYPES`; `"all"` keeps everything.
- `min_distance_m` keeps activities whose Garmin distance is at least that;
  activities without a distance drop out when the filter is set.
- Order: `start_time_local` descending, then `activity_id` descending.
- `total` counts every activity that passes the filters, for paging.
"""

from pathlib import Path
from typing import Literal, TypedDict

from running.config import RunWalk
from running.db import AnalysisDb, open_analysis_db
from running.runwalk import RUNNING_TYPES, running_summaries
from running.section import Method, section_inputs

TypeFilter = Literal["running", "all"]
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class ActivityRow(TypedDict):
    activity_id: int
    activity_type: str
    activity_name: str | None
    start_time_local: str
    distance_m: float | None
    duration_s: float | None
    running_pace_s_per_km: float | None  # running types only, walking left out
    avg_hr_bpm: float | None


class ActivityList(TypedDict):
    has_data: bool  # the analysis database holds at least one activity
    type_filter: TypeFilter
    min_distance_m: float | None
    page: int
    page_size: int
    total: int  # activities passing the filters
    activities: list[ActivityRow]
    method: Method


def _where(type_filter: TypeFilter, min_distance_m: float | None) -> tuple[str, list]:
    clauses, params = [], []
    if type_filter == "running":
        types = sorted(RUNNING_TYPES)
        clauses.append(f"activity_type IN ({', '.join('?' for _ in types)})")
        params += types
    if min_distance_m is not None:
        clauses.append("distance_m >= ?")
        params.append(min_distance_m)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _page_rows(
    db: AnalysisDb,
    type_filter: TypeFilter,
    min_distance_m: float | None,
    page: int,
    page_size: int,
) -> tuple[int, list[dict]]:
    where, params = _where(type_filter, min_distance_m)
    total = int(db.query(f"SELECT count(*) FROM a.activities{where}", params).item())
    rows = db.query(
        "SELECT activity_id, activity_type, activity_name, start_time_local,"
        " distance_m, duration_s, avg_hr_bpm"
        f" FROM a.activities{where}"
        " ORDER BY start_time_local DESC, activity_id DESC LIMIT ? OFFSET ?",
        [*params, page_size, (page - 1) * page_size],
    )
    return total, rows.to_dicts()


def _running_paces(db: AnalysisDb, rows: list[dict], settings: RunWalk) -> dict[int, float]:
    """Running pace of the running-type rows on this page (walking left out)."""
    ids = [r["activity_id"] for r in rows if r["activity_type"] in RUNNING_TYPES]
    summaries = running_summaries(db, settings, activity_ids=ids)
    return {
        r["activity_id"]: r["run_pace_s_per_km"]
        for r in summaries.iter_rows(named=True)
        if r["run_pace_s_per_km"] is not None
    }


def activity_list(
    type_filter: TypeFilter = "running",
    min_distance_m: float | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    root: Path | None = None,
) -> ActivityList:
    inputs = section_inputs(None, root)
    has_data, total, rows, paces = False, 0, [], {}
    db = open_analysis_db(inputs.root)
    if db is not None:
        with db:
            if "activities" in db.tables():
                has_data = bool(db.query("SELECT count(*) FROM a.activities").item())
                total, rows = _page_rows(db, type_filter, min_distance_m, page, page_size)
                paces = _running_paces(db, rows, inputs.config.run_walk)
    return {
        "has_data": has_data,
        "type_filter": type_filter,
        "min_distance_m": min_distance_m,
        "page": page,
        "page_size": page_size,
        "total": total,
        "activities": [{**r, "running_pace_s_per_km": paces.get(r["activity_id"])} for r in rows],
        "method": _method(inputs.config.run_walk),
    }


def _method(settings: RunWalk) -> Method:
    return {
        "name": "活动列表",
        "description": (
            "按开始时间（当地时间）从新到旧列出活动。默认只列跑步类活动，可以切换为全部类型；"
            "最小距离按 Garmin 记录的距离筛选，没有距离的活动在设了最小距离时不列出。"
            "跑步配速只算跑的秒：步频（双脚）按 "
            f"{settings.smoothing_s} 秒平滑后 ≥ {settings.cadence_spm:g} spm 算跑，"
            f"短于 {settings.min_walk_s} 秒的走路仍算跑，"
            f"采样间隔超过 {settings.pause_gap_s} 秒算暂停，不计时间和距离。"
            "没有步频数据的活动用 Garmin 的总距离和总时长。非跑步类活动不给跑步配速。"
        ),
        "params": {
            "running_types": sorted(RUNNING_TYPES),
            "cadence_spm": settings.cadence_spm,
            "smoothing_s": settings.smoothing_s,
            "min_walk_s": settings.min_walk_s,
            "pause_gap_s": settings.pause_gap_s,
            "max_page_size": MAX_PAGE_SIZE,
        },
    }
