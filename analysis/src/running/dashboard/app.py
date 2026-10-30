"""The local dashboard: FastAPI on 127.0.0.1 serving JSON from `running`
and the static frontend in `static/`. No accounts, no writes."""

from datetime import date
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from running.status import DataStatus, data_status
from running.volume import Volume, weekly_volume

HOST = "127.0.0.1"
PORT = 8765
STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="running dashboard", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/api/status")
    def status() -> DataStatus:
        return data_status()

    @app.get("/api/volume")
    def volume(today: date | None = None) -> Volume:
        return weekly_volume(today=today)

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


def main() -> None:
    import uvicorn

    print(f"仪表盘：http://{HOST}:{PORT}/")
    uvicorn.run(create_app(), host=HOST, port=PORT)
