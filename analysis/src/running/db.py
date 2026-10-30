"""Read-only access to the analysis database (`running.sqlite`, written by
the Rust importer). DuckDB attaches the SQLite file read-only; results come
back as polars DataFrames. Python never writes to this database."""

from pathlib import Path

import duckdb
import polars as pl

from running.config import analysis_db_path

ALIAS = "a"


class AnalysisDb:
    """A read-only DuckDB connection with the analysis database attached as `a`.

    Tables are addressed as `a.activities`, `a.sync_runs`, ...
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._con = duckdb.connect(":memory:")
        escaped = str(path).replace("'", "''")
        self._con.execute(f"ATTACH '{escaped}' AS {ALIAS} (TYPE sqlite, READ_ONLY)")

    def query(self, sql: str, params: list | None = None) -> pl.DataFrame:
        # Polars reads the relation through the Arrow C stream interface,
        # so neither pyarrow nor pandas is needed.
        return pl.DataFrame(self._con.sql(sql, params=params or None))

    def tables(self) -> set[str]:
        rows = self._con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_catalog = ?", [ALIAS]
        ).fetchall()
        return {r[0] for r in rows}

    def close(self) -> None:
        self._con.close()

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
