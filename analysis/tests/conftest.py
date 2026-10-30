"""Shared fixtures: a temp data directory and a synthetic analysis database
built with the importer's own migration SQL, so the schema matches Rust."""

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from running.dashboard.app import create_app

MIGRATIONS = Path(__file__).resolve().parents[2] / "importer" / "migrations"

CONFIG_TOML = """\
[aerobic]
reference_hr = 145

[[physiology]]
effective_from = 2021-08-01
hr_max = 192
hr_rest = 55
lthr = 170
"""


def create_analysis_db(path: Path) -> sqlite3.Connection:
    """Create `running.sqlite` at the importer's latest schema version."""
    conn = sqlite3.connect(path)
    files = sorted(MIGRATIONS.glob("*.sql"))
    assert files, f"no migrations in {MIGRATIONS}"
    for f in files:
        conn.executescript(f.read_text(encoding="utf-8"))
    conn.execute(f"PRAGMA user_version = {len(files)}")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.commit()
    return conn


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "running-data"
    d.mkdir()
    (d / "config.toml").write_text(CONFIG_TOML, encoding="utf-8")
    monkeypatch.setenv("RUNNING_DATA_DIR", str(d))
    return d


@pytest.fixture
def analysis_db(data_dir: Path):
    conn = create_analysis_db(data_dir / "running.sqlite")
    yield conn
    conn.close()


@pytest.fixture
def client_factory() -> Callable[[], TestClient]:
    """Build the app after the test has arranged the data directory."""
    return lambda: TestClient(create_app())
