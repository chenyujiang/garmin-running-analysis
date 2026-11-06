"""Read-only access to the analysis database (`running.sqlite`, written by
the Rust importer). DuckDB attaches the SQLite file read-only; results come
back as polars DataFrames. Python never writes to this database.

DuckDB's SQLite scan cannot use SQLite's indexes, so a query on `records`
(millions of rows) reads the whole table even for one activity. Queries on a
few activities' records go through `query_records`, which reads them by
primary key with Python's sqlite3 (read-only) and keeps them for the life of
the connection, so one request reads each activity once."""

import sqlite3
import threading
import time
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


def _connect(path: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    escaped = str(path).replace("'", "''")
    con.execute(f"ATTACH '{escaped}' AS {ALIAS} (TYPE sqlite, READ_ONLY)")
    return con


def _file_version(path: Path) -> tuple[tuple[int, int], ...]:
    version = []
    for f in (path, path.with_name(path.name + "-wal")):
        try:
            st = f.stat()
            version.append((st.st_mtime_ns, st.st_size))
        except FileNotFoundError:
            version.append((0, 0))
    return tuple(version)


# Shared connections (off unless `enable_shared_connections` is called; the
# dashboard turns them on). Connecting and attaching the SQLite file takes
# about 0.2 s, so one DuckDB instance per database file is kept and each
# `AnalysisDb` takes its own cursor from it. DuckDB keeps temp tables, views
# and registered frames per cursor, so concurrent requests do not see each
# other's `recs`. The instance is replaced when the file or its WAL changes
# (a sync, or `runsync rebuild` recreating the file), and closed after
# `idle_s` seconds without users to free its memory. DuckDB's SQLite scan does
# not keep the file open between queries, so an open instance does not stop
# `runsync rebuild` from deleting it.
class _Shared:
    def __init__(self, path: Path, version: tuple) -> None:
        self.version = version
        self.con = _connect(path)
        self.users = 0
        self.retired = False
        self.idle_since: float | None = None


_shared_lock = threading.Lock()
_shared: dict[Path, _Shared] = {}
_shared_idle_s: float | None = None
_reaper: threading.Timer | None = None


def enable_shared_connections(idle_s: float = 600.0) -> None:
    """Share one DuckDB instance per database file between `AnalysisDb`s,
    closing it after `idle_s` seconds without users."""
    global _shared_idle_s
    with _shared_lock:
        _shared_idle_s = idle_s


def disable_shared_connections() -> None:
    """Stop sharing and close every idle shared instance; instances still in
    use close when their last user does."""
    global _shared_idle_s, _reaper
    with _shared_lock:
        _shared_idle_s = None
        if _reaper is not None:
            _reaper.cancel()
            _reaper = None
        for entry in _shared.values():
            entry.retired = True
            if entry.users == 0:
                entry.con.close()
        _shared.clear()


def _checkout(path: Path) -> tuple[_Shared, duckdb.DuckDBPyConnection] | None:
    """A cursor on the shared instance for `path`, or None when sharing is off."""
    key = path.resolve()
    version = _file_version(path)
    with _shared_lock:
        if _shared_idle_s is None:
            return None
        entry = _shared.get(key)
        if entry is not None and entry.version != version:
            del _shared[key]
            entry.retired = True
            if entry.users == 0:
                entry.con.close()
            entry = None
        if entry is None:
            entry = _Shared(path, version)
            _shared[key] = entry
        entry.users += 1
        entry.idle_since = None
        return entry, entry.con.cursor()


def _release(entry: _Shared) -> None:
    global _reaper
    with _shared_lock:
        entry.users -= 1
        if entry.users > 0:
            return
        if entry.retired:
            entry.con.close()
            return
        entry.idle_since = time.monotonic()
        if _reaper is None and _shared_idle_s is not None:
            _reaper = threading.Timer(_shared_idle_s, _close_idle)
            _reaper.daemon = True
            _reaper.start()


def _close_idle() -> None:
    """Close shared instances idle for `_shared_idle_s`; wait again for the rest."""
    global _reaper
    with _shared_lock:
        _reaper = None
        if _shared_idle_s is None:
            return
        now = time.monotonic()
        next_due: float | None = None
        for key, entry in list(_shared.items()):
            if entry.users > 0 or entry.idle_since is None:
                continue
            due = entry.idle_since + _shared_idle_s
            if due <= now:
                del _shared[key]
                entry.con.close()
            else:
                next_due = due if next_due is None else min(next_due, due)
        if next_due is not None:
            _reaper = threading.Timer(next_due - now, _close_idle)
            _reaper.daemon = True
            _reaper.start()


class AnalysisDb:
    """A read-only DuckDB connection with the analysis database attached as `a`.

    Tables are addressed as `a.activities`, `a.sync_runs`, ... With shared
    connections on (`enable_shared_connections`), this is a cursor on the
    shared instance for the file; otherwise a connection of its own.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        checkout = _checkout(path)
        if checkout is None:
            self._entry: _Shared | None = None
            self._con = _connect(path)
        else:
            self._entry, self._con = checkout
        self._closed = False
        self._sqlite: sqlite3.Connection | None = None
        self._records: dict[int, pl.DataFrame] = {}
        self._tables: frozenset[str] | None = None
        self._recs_ids: tuple[int, ...] | None = None  # activities in the temp table `recs`

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
            self._drop_recs_table()
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
        # The table stays until other activities are asked for: a detail page
        # queries the same activity's records several times.
        if self._recs_ids != tuple(ids):
            self._drop_recs_table()
            self._con.register("_recs_stream", _ArrowStream(self._indexed_records(ids)))
            try:
                self._con.execute("CREATE TEMP TABLE recs AS SELECT * FROM _recs_stream")
            finally:
                self._con.unregister("_recs_stream")
            self._recs_ids = tuple(ids)
        return self.query(sql, params)

    def _drop_recs_table(self) -> None:
        if self._recs_ids is not None:
            self._con.execute("DROP TABLE IF EXISTS recs")
            self._recs_ids = None

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
        return _file_version(self.path)

    def tables(self) -> set[str]:
        """Table names of the attached database, read once per `AnalysisDb`."""
        if self._tables is None:
            rows = self._con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_catalog = ?", [ALIAS]
            ).fetchall()
            self._tables = frozenset(r[0] for r in rows)
        return set(self._tables)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._con.close()
        if self._entry is not None:
            _release(self._entry)
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
