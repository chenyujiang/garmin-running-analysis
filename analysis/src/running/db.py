"""Read-only access to the analysis database (`running.sqlite`, written by
the Rust importer). DuckDB attaches the SQLite file read-only; results come
back as polars DataFrames. Python never writes to this database.

DuckDB's SQLite scan cannot use SQLite's indexes, so a query on `records`
(millions of rows) reads the whole table even for one activity. Queries on a
few activities' records go through `query_records`, which reads them by
primary key with Python's sqlite3 (read-only) and keeps them for the life of
the connection, so one request reads each activity once."""

import sqlite3
from pathlib import Path

import duckdb
import polars as pl

from running.config import analysis_db_path

ALIAS = "a"

# Up to this many activities, `query_records` reads them through SQLite's
# primary key; more than that and DuckDB's full scan is faster.
MAX_INDEXED_ACTIVITIES = 64

RECORD_COLUMNS = {
    "activity_id": pl.Int64,
    "timestamp": pl.String,
    "heart_rate": pl.Float64,
    "speed": pl.Float64,
    "cadence": pl.Float64,
    "altitude": pl.Float64,
    "distance": pl.Float64,
    "lat": pl.Float64,
    "lon": pl.Float64,
}


class _ArrowStream:
    """Exposes only a frame's Arrow C stream, which DuckDB reads without pyarrow."""

    def __init__(self, frame: pl.DataFrame) -> None:
        self._frame = frame

    def __arrow_c_stream__(self, requested_schema=None):  # noqa: ANN001, ANN204
        return self._frame.__arrow_c_stream__(requested_schema)


class AnalysisDb:
    """A read-only DuckDB connection with the analysis database attached as `a`.

    Tables are addressed as `a.activities`, `a.sync_runs`, ...
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._con = duckdb.connect(":memory:")
        escaped = str(path).replace("'", "''")
        self._con.execute(f"ATTACH '{escaped}' AS {ALIAS} (TYPE sqlite, READ_ONLY)")
        self._sqlite: sqlite3.Connection | None = None
        self._records: dict[int, pl.DataFrame] = {}

    def query(self, sql: str, params: list | None = None) -> pl.DataFrame:
        # Polars reads the relation through the Arrow C stream interface,
        # so neither pyarrow nor pandas is needed.
        return pl.DataFrame(self._con.sql(sql, params=params or None))

    def query_records(
        self, sql: str, activity_ids: list[int], params: list | None = None
    ) -> pl.DataFrame:
        """Run `sql` with the relation `recs` holding the `records` rows of
        `activity_ids` (columns `RECORD_COLUMNS`). `recs` must be the only way
        `sql` reads records."""
        ids = sorted({int(i) for i in activity_ids})
        if len(ids) > MAX_INDEXED_ACTIVITIES:
            id_list = ", ".join(str(i) for i in ids) or "NULL"
            cols = ", ".join(RECORD_COLUMNS)
            self._con.execute(
                f"CREATE OR REPLACE TEMP VIEW recs AS SELECT {cols}"
                f" FROM {ALIAS}.records WHERE activity_id IN ({id_list})"
            )
            try:
                return self.query(sql, params)
            finally:
                self._con.execute("DROP VIEW IF EXISTS recs")
        # DuckDB reads the frame through the Arrow C stream interface (no
        # pyarrow); a stream is read once, so it lands in a temp table first.
        self._con.register("_recs_stream", _ArrowStream(self._indexed_records(ids)))
        try:
            self._con.execute("CREATE OR REPLACE TEMP TABLE recs AS SELECT * FROM _recs_stream")
        finally:
            self._con.unregister("_recs_stream")
        try:
            return self.query(sql, params)
        finally:
            self._con.execute("DROP TABLE IF EXISTS recs")

    def _indexed_records(self, ids: list[int]) -> pl.DataFrame:
        missing = [i for i in ids if i not in self._records]
        if missing:
            if self._sqlite is None:
                uri = self.path.resolve().as_uri() + "?mode=ro"
                self._sqlite = sqlite3.connect(uri, uri=True)
            cols = ", ".join(RECORD_COLUMNS)
            for i in missing:
                rows = self._sqlite.execute(
                    f"SELECT {cols} FROM records WHERE activity_id = ? ORDER BY timestamp", [i]
                ).fetchall()
                self._records[i] = pl.DataFrame(rows, schema=RECORD_COLUMNS, orient="row")
        frames = [self._records[i] for i in ids]
        return pl.concat(frames) if frames else pl.DataFrame(schema=RECORD_COLUMNS)

    def file_version(self) -> tuple[tuple[int, int], ...]:
        """(mtime_ns, size) of the database file and its `-wal` file; any
        write to the database changes one of them."""
        version = []
        for f in (self.path, self.path.with_name(self.path.name + "-wal")):
            try:
                st = f.stat()
                version.append((st.st_mtime_ns, st.st_size))
            except FileNotFoundError:
                version.append((0, 0))
        return tuple(version)

    def tables(self) -> set[str]:
        rows = self._con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_catalog = ?", [ALIAS]
        ).fetchall()
        return {r[0] for r in rows}

    def close(self) -> None:
        self._con.close()
        if self._sqlite is not None:
            self._sqlite.close()

    def __enter__(self) -> AnalysisDb:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def open_analysis_db(root: Path | None = None) -> AnalysisDb | None:
    """Open the analysis database read-only, or None if it does not exist yet."""
    path = analysis_db_path(root)
    if not path.is_file():
        return None
    return AnalysisDb(path)
