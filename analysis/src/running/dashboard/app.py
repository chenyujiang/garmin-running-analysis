"""The local dashboard: FastAPI on 127.0.0.1 serving JSON from `running`
and the static frontend in `static/`. No accounts, no writes (it only reads
what `running-push-plan` recorded in `state/`)."""

import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from running.activities import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ActivityList,
    TypeFilter,
    activity_list,
)
from running.aerobic import AerobicTrend, Range, aerobic_trend
from running.config import data_dir
from running.console import utf8_stdio
from running.db import disable_shared_connections, enable_shared_connections, open_analysis_db
from running.detail import ActivityDetail, activity_detail
from running.load import TrainingLoad, training_load
from running.longruns import LongRuns, long_runs
from running.plan5k import Plan5k, plan_5k
from running.plan_review import PlanReview, plan_review
from running.push_plan import STATE_FILE, PushStatus, load_state, push_status
from running.races import Predictions, RaceList, race_list, race_predictions
from running.runwalk import running_summaries
from running.section import section_inputs
from running.status import DataStatus, data_status
from running.volume import Volume, weekly_volume


class Plan5kView(Plan5k):
    push: PushStatus | None  # the last `running-push-plan --apply`, if any


HOST = "127.0.0.1"
PORT = 8765
STATIC_DIR = Path(__file__).resolve().parent / "static"


# Seconds a shared DuckDB instance stays open without requests before it is
# closed to free memory (see `running.db.enable_shared_connections`).
SHARED_IDLE_S = 600.0


@asynccontextmanager
async def _serve_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """For the served dashboard only: share DuckDB connections between
    requests and fill the caches in the background."""
    enable_shared_connections(SHARED_IDLE_S)
    stop = threading.Event()
    warm = threading.Thread(
        target=_warm_caches, args=(data_dir(), stop), name="warm-caches", daemon=True
    )
    warm.start()
    try:
        yield
    finally:
        stop.set()
        warm.join(timeout=30)
        disable_shared_connections()


def create_app(*, serve: bool = False) -> FastAPI:
    """The dashboard app. `serve=True` (the `running-dashboard` server) also
    shares DuckDB connections and warms the caches at startup."""
    app = FastAPI(
        title="running dashboard",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_serve_lifespan if serve else None,
    )

    @app.get("/api/activities")
    def activities(
        type: TypeFilter = "running",  # noqa: A002
        min_km: float | None = Query(None, ge=0),
        page: int = Query(1, ge=1),
        page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
        q: str | None = Query(None, max_length=100),
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> ActivityList:
        min_m = None if min_km is None else min_km * 1000.0
        return activity_list(
            type_filter=type,
            min_distance_m=min_m,
            page=page,
            page_size=page_size,
            query=q,
            date_from=date_from,
            date_to=date_to,
        )

    @app.get("/api/activities/{activity_id}")
    def activity(activity_id: int) -> ActivityDetail:
        detail = activity_detail(activity_id)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"没有编号为 {activity_id} 的活动。")
        return detail

    @app.get("/api/status")
    def status() -> DataStatus:
        return data_status()

    @app.get("/api/load")
    def load(today: date | None = None) -> TrainingLoad:
        return training_load(today=today)

    @app.get("/api/volume")
    def volume(today: date | None = None) -> Volume:
        return weekly_volume(today=today)

    @app.get("/api/aerobic")
    def aerobic(range: Range = "1y", today: date | None = None) -> AerobicTrend:  # noqa: A002
        return aerobic_trend(range_=range, today=today)

    @app.get("/api/long-runs")
    def long_runs_table(
        today: date | None = None, limit: int = Query(10, ge=1, le=100)
    ) -> LongRuns:
        return long_runs(today=today, limit=limit)

    @app.get("/api/predictions")
    def predictions(today: date | None = None) -> Predictions:
        return race_predictions(today=today)

    @app.get("/api/races")
    def races(today: date | None = None) -> RaceList:
        return race_list(today=today)

    @app.get("/api/plan5k")
    def plan5k(
        today: date | None = None,
        target_s: float = Query(1200, ge=600, le=3600),
        current_s: float | None = Query(None, ge=600, le=3600),
        days: str = Query("2,3,4,6", pattern=r"^[1-7](,[1-7])*$"),
        parkrun_day: int = Query(6, ge=0, le=7),  # 0: no parkrun
    ) -> Plan5kView:
        try:
            plan = plan_5k(
                today=today,
                target_s=target_s,
                current_s=current_s,
                days=[int(d) for d in days.split(",")],
                parkrun_day=parkrun_day or None,
            )
        except ValueError as err:
            raise HTTPException(status_code=422, detail=str(err)) from err
        try:
            push = push_status(plan, load_state(data_dir() / "state" / STATE_FILE))
        except (OSError, ValueError, KeyError, TypeError) as err:
            push = None
            plan["warnings"].append(f"读不了 state/{STATE_FILE}，没标出已推送的计划课：{err}")
        return {**plan, "push": push}

    @app.get("/api/plan-review")
    def plan_review_view(today: date | None = None) -> PlanReview:
        return plan_review(today=today)

    app.mount("/", _RevalidatedStaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


class _RevalidatedStaticFiles(StaticFiles):
    """Static files the browser must revalidate (ETag) before each use, so an
    edited style.css or app.js shows on the next page load."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def main() -> None:
    import uvicorn

    utf8_stdio()
    print(f"仪表盘：http://{HOST}:{PORT}/")
    uvicorn.run(create_app(serve=True), host=HOST, port=PORT)


def _warm_caches(root: Path, stop: threading.Event) -> None:
    """Fill the per-process caches (heart-rate seconds, aerobic per-run
    results, long-run EF, run-walk record totals) once at startup, so the
    first page load does not pay for the full scans of `records`. A failure
    here only means a cold first request; the endpoint reports the error itself."""
    for warm in (
        training_load,
        aerobic_trend,
        race_predictions,
        weekly_volume,
        long_runs,
        _warm_run_summaries,
    ):
        if stop.is_set():
            return
        try:
            warm(root=root)
        except Exception:  # noqa: BLE001, S112
            continue


def _warm_run_summaries(root: Path) -> None:
    """Record totals of every run, so filtering the activity list (distance,
    dates, older pages) does not read records on first use."""
    inputs = section_inputs(None, root)
    db = open_analysis_db(inputs.root)
    if db is None:
        return
    with db:
        running_summaries(db, inputs.config.run_walk)
