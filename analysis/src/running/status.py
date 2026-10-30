"""Data status: has anything been synced, how much, and when."""

from pathlib import Path
from typing import TypedDict

from running.config import ConfigError, data_dir, load_config
from running.db import open_analysis_db


class DataStatus(TypedDict):
    data_dir: str
    has_data: bool
    activity_count: int
    last_sync_utc: str | None
    latest_activity_local: str | None
    config_error: str | None


def data_status(root: Path | None = None) -> DataStatus:
    root = root or data_dir()
    status: DataStatus = {
        "data_dir": str(root),
        "has_data": False,
        "activity_count": 0,
        "last_sync_utc": None,
        "latest_activity_local": None,
        "config_error": None,
    }
    try:
        load_config(root)
    except ConfigError as err:
        status["config_error"] = str(err)

    db = open_analysis_db(root) if root.is_dir() else None
    if db is None:
        return status
    with db:
        tables = db.tables()
        if "activities" in tables:
            row = db.query(
                "SELECT count(*) AS n, max(start_time_local) AS latest FROM a.activities"
            ).row(0, named=True)
            status["activity_count"] = int(row["n"])
            status["latest_activity_local"] = row["latest"]
        if "sync_runs" in tables:
            status["last_sync_utc"] = db.query(
                "SELECT max(finished_at_utc) AS t FROM a.sync_runs"
            ).item()
    status["has_data"] = status["activity_count"] > 0
    return status
