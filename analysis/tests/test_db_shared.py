"""Shared DuckDB connections (`enable_shared_connections`): `AnalysisDb`s on
the same file reuse one instance, a write to the file brings a fresh one, an
idle instance closes, and concurrent requests each see their own `recs`."""

import os
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from synthetic import add_run, run, walk

from running import db as dbmod
from running.dashboard.app import create_app
from running.db import AnalysisDb, disable_shared_connections, enable_shared_connections


@pytest.fixture(autouse=True)
def _sharing_off_afterwards():
    yield
    disable_shared_connections()


def _seed(conn, ids: list[int]) -> None:
    for i, aid in enumerate(ids):
        add_run(conn, aid, f"2026-10-{1 + i:02d}T06:00:00", [run(60 + i), walk(10)])
    conn.commit()


def _count(db: AnalysisDb, aid: int) -> int:
    return db.query_records("SELECT count(*) AS n FROM recs", [aid])["n"].item()


def test_off_by_default(analysis_db, data_dir: Path) -> None:
    _seed(analysis_db, [1])
    with AnalysisDb(data_dir / "running.sqlite") as db:
        assert db._entry is None
        assert _count(db, 1) == 71
    assert dbmod._shared == {}


def test_reuses_one_instance_until_the_file_changes(analysis_db, data_dir: Path) -> None:
    _seed(analysis_db, [1])
    enable_shared_connections(idle_s=60)
    path = data_dir / "running.sqlite"
    with AnalysisDb(path) as a:
        first = a._entry
        assert _count(a, 1) == 71
    with AnalysisDb(path) as b:
        assert b._entry is first
        assert _count(b, 1) == 71

    time.sleep(0.01)  # a new mtime even on coarse clocks
    _seed(analysis_db, [2])
    with AnalysisDb(path) as c:
        assert c._entry is not first
        assert _count(c, 2) == 71
    assert first.retired


def test_idle_instance_closes_and_the_file_can_be_deleted(analysis_db, data_dir: Path) -> None:
    _seed(analysis_db, [1])
    analysis_db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    analysis_db.close()
    enable_shared_connections(idle_s=0.05)
    path = data_dir / "running.sqlite"
    with AnalysisDb(path) as db:
        assert _count(db, 1) == 71
    deadline = time.monotonic() + 5
    while dbmod._shared and time.monotonic() < deadline:
        time.sleep(0.02)
    assert dbmod._shared == {}
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(path) + suffix)
        if p.exists():
            os.remove(p)  # what `runsync rebuild` does
    assert not path.exists()


def test_concurrent_requests_see_their_own_recs(analysis_db, data_dir: Path) -> None:
    ids = list(range(1, 9))
    _seed(analysis_db, ids)
    enable_shared_connections(idle_s=60)
    path = data_dir / "running.sqlite"
    results: dict[int, list[int]] = {}
    errors: list[BaseException] = []
    start = threading.Barrier(len(ids))

    def work(aid: int) -> None:
        try:
            start.wait()
            with AnalysisDb(path) as db:
                results[aid] = [_count(db, aid) for _ in range(5)]
        except BaseException as err:  # noqa: BLE001
            errors.append(err)

    threads = [threading.Thread(target=work, args=(aid,)) for aid in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert results == {aid: [60 + (aid - 1) + 11] * 5 for aid in ids}
    assert len(dbmod._shared) == 1


def test_served_app_shares_connections_only_while_running(analysis_db, data_dir: Path) -> None:
    _seed(analysis_db, [1])
    with TestClient(create_app(serve=True)) as client:
        assert client.get("/api/status").status_code == 200
        assert dbmod._shared_idle_s is not None
    assert dbmod._shared_idle_s is None
    assert dbmod._shared == {}

    with TestClient(create_app()) as client:
        assert client.get("/api/status").status_code == 200
        assert dbmod._shared_idle_s is None
