"""The local dashboard: FastAPI on 127.0.0.1 serving JSON from `running`
and the static frontend in `static/`. No accounts, no writes."""

import io
import sys
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
from running.detail import ActivityDetail, activity_detail
from running.load import TrainingLoad, training_load
from running.longruns import LongRuns, long_runs
from running.plan5k import Plan5k, plan_5k
from running.races import Predictions, RaceList, race_list, race_predictions
from running.status import DataStatus, data_status
from running.volume import Volume, weekly_volume

HOST = "127.0.0.1"
PORT = 8765
STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="running dashboard", docs_url=None, redoc_url=None, openapi_url=None)

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
    ) -> Plan5k:
        try:
            return plan_5k(
                today=today,
                target_s=target_s,
                current_s=current_s,
                days=[int(d) for d in days.split(",")],
                parkrun_day=parkrun_day or None,
            )
        except ValueError as err:
            raise HTTPException(status_code=422, detail=str(err)) from err

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

    # A console or pipe that is not UTF-8 (e.g. cp1252) cannot encode the
    # Chinese startup line; write UTF-8 and replace anything unencodable.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"仪表盘：http://{HOST}:{PORT}/")
    uvicorn.run(create_app(), host=HOST, port=PORT)
