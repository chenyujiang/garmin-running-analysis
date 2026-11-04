"""`AnalysisDb.query_records`: per-activity reads through the SQLite primary
key give the same rows as the DuckDB scan, on both the indexed path (few
activities) and the view path (more than `MAX_INDEXED_ACTIVITIES`)."""

from pathlib import Path

from synthetic import add_run, run, walk

from running.db import MAX_INDEXED_ACTIVITIES, AnalysisDb

SQL = (
    "SELECT activity_id, count(*) AS n, sum(speed) AS speed, max(distance) AS dist"
    " FROM {src} WHERE activity_id IN ({ids}) GROUP BY activity_id ORDER BY activity_id"
)


def _seed(conn, count: int) -> list[int]:
    ids = [1000 + i for i in range(count)]
    for i, aid in enumerate(ids):
        add_run(
            conn,
            aid,
            f"2026-10-{1 + i % 28:02d}T{6 + i // 28:02d}:00:00",
            [run(60 + i), walk(10), run(30)],
        )
    return ids


def _both(db: AnalysisDb, ids: list[int]):
    in_list = ",".join(str(i) for i in ids)
    old = db.query(SQL.format(src="a.records", ids=in_list))
    new = db.query_records(SQL.format(src="recs", ids=in_list), ids)
    return old, new


def test_indexed_path_matches_scan(analysis_db, data_dir: Path) -> None:
    ids = _seed(analysis_db, 3)
    with AnalysisDb(data_dir / "running.sqlite") as db:
        old, new = _both(db, ids[:2])
        assert new.equals(old)
        assert new["n"].to_list() == [101, 102]
        # Second call reuses the cached frames, still the same rows.
        assert db.query_records(SQL.format(src="recs", ids="1000"), [1000])["n"].item() == 101


def test_view_path_matches_scan(analysis_db, data_dir: Path) -> None:
    ids = _seed(analysis_db, MAX_INDEXED_ACTIVITIES + 1)
    with AnalysisDb(data_dir / "running.sqlite") as db:
        old, new = _both(db, ids)
        assert new.height == len(ids)
        assert new.equals(old)


def test_unknown_activity_gives_no_rows(analysis_db, data_dir: Path) -> None:
    _seed(analysis_db, 1)
    with AnalysisDb(data_dir / "running.sqlite") as db:
        assert db.query_records("SELECT count(*) AS n FROM recs", [9999])["n"].item() == 0
