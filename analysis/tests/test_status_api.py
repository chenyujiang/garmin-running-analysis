"""Seam 3: the dashboard's data-status endpoint, GET /api/status."""

from pathlib import Path


def insert_activity(conn, activity_id: int, start_local: str, start_utc: str) -> None:
    conn.execute(
        "INSERT INTO activities (activity_id, activity_type, start_time_utc, start_time_local,"
        " distance_m, duration_s) VALUES (?, 'running', ?, ?, 10000.0, 3600.0)",
        (activity_id, start_utc, start_local),
    )
    conn.commit()


def insert_sync_run(conn, finished_utc: str, source: str = "personal_api") -> None:
    conn.execute(
        "INSERT INTO sync_runs (source, started_at_utc, finished_at_utc, outcome)"
        " VALUES (?, ?, ?, 'ok')",
        (source, finished_utc, finished_utc),
    )
    conn.commit()


def test_without_an_analysis_database_reports_no_data(data_dir: Path, client_factory):
    r = client_factory().get("/api/status")

    assert r.status_code == 200
    assert r.json() == {
        "data_dir": str(data_dir),
        "has_data": False,
        "activity_count": 0,
        "last_sync_utc": None,
        "latest_activity_local": None,
        "config_error": None,
    }


def test_an_empty_analysis_database_reports_no_data(data_dir: Path, analysis_db, client_factory):
    body = client_factory().get("/api/status").json()

    assert body["has_data"] is False
    assert body["activity_count"] == 0
    assert body["last_sync_utc"] is None


def test_with_activities_reports_count_and_latest_sync(analysis_db, client_factory):
    insert_activity(analysis_db, 1, "2026-10-08T11:08:46", "2026-10-07T22:08:46Z")
    insert_activity(analysis_db, 2, "2026-10-20T07:00:00", "2026-10-19T18:00:00Z")
    insert_activity(analysis_db, 3, "2026-09-01T06:30:00", "2026-08-31T18:30:00Z")
    insert_sync_run(analysis_db, "2026-10-20T09:15:00Z")
    insert_sync_run(analysis_db, "2026-10-28T08:00:00Z", source="garminconnect")
    insert_sync_run(analysis_db, "2026-10-25T08:00:00Z")

    body = client_factory().get("/api/status").json()

    assert body["has_data"] is True
    assert body["activity_count"] == 3
    assert body["last_sync_utc"] == "2026-10-28T08:00:00Z"
    assert body["latest_activity_local"] == "2026-10-20T07:00:00"


def test_activities_without_any_sync_run_still_count_as_data(analysis_db, client_factory):
    insert_activity(analysis_db, 1, "2026-10-08T11:08:46", "2026-10-07T22:08:46Z")

    body = client_factory().get("/api/status").json()

    assert body["has_data"] is True
    assert body["activity_count"] == 1
    assert body["last_sync_utc"] is None


def test_a_missing_config_file_is_reported(data_dir: Path, client_factory):
    (data_dir / "config.toml").unlink()

    body = client_factory().get("/api/status").json()

    assert "config.toml" in body["config_error"]


def test_a_missing_data_directory_is_reported(tmp_path: Path, monkeypatch, client_factory):
    missing = tmp_path / "nope"
    monkeypatch.setenv("RUNNING_DATA_DIR", str(missing))

    body = client_factory().get("/api/status").json()

    assert body["data_dir"] == str(missing)
    assert body["has_data"] is False
    assert "nope" in body["config_error"]


def test_the_status_read_does_not_modify_the_analysis_database(
    data_dir: Path, analysis_db, client_factory
):
    insert_activity(analysis_db, 1, "2026-10-08T11:08:46", "2026-10-07T22:08:46Z")
    db = data_dir / "running.sqlite"
    before = db.read_bytes()

    client_factory().get("/api/status")

    assert db.read_bytes() == before


def test_the_dashboard_page_is_served(data_dir: Path, client_factory):
    r = client_factory().get("/")

    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert 'lang="zh-CN"' in r.text
