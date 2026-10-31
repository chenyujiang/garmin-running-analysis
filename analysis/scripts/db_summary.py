"""Print aggregate numbers from the analysis database, for read-only checks on
real data: row counts, date ranges and NULL counts per table, then the
aerobic-capacity totals (valid road runs, runs with air temperature, hot
weeks).

Opens `running.sqlite` read-only (`mode=ro`). The only values printed are
counts and the min/max of date and time columns, so no coordinate, grid
point or other personal value ever reaches the output.

Run from analysis/:  uv run python scripts/db_summary.py
(set RUNNING_DATA_DIR to read another data directory)
"""

import sqlite3
import sys
from pathlib import Path

from running.aerobic import aerobic_trend
from running.config import analysis_db_path, data_dir


def _is_time_column(name: str) -> bool:
    return name == "date" or name.endswith(("_utc", "_local", "_date"))


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def table_lines(conn: sqlite3.Connection) -> list[str]:
    lines = []
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    for table in tables:
        columns = [r[1] for r in conn.execute(f"PRAGMA table_info({_quote(table)})")]
        time_columns = [c for c in columns if _is_time_column(c)]
        parts = ["count(*)"]
        parts += [f"sum({_quote(c)} IS NULL)" for c in columns]
        parts += [f"min({_quote(c)}), max({_quote(c)})" for c in time_columns]
        row = conn.execute(f"SELECT {', '.join(parts)} FROM {_quote(table)}").fetchone()
        count, rest = row[0], row[1:]
        nulls, ranges = rest[: len(columns)], rest[len(columns) :]

        lines.append(f"{table}: {count} rows")
        for i, c in enumerate(time_columns):
            lo, hi = ranges[2 * i], ranges[2 * i + 1]
            if lo is not None:
                lines.append(f"  {c}: {lo} .. {hi}")
        with_nulls = [f"{c}={n}" for c, n in zip(columns, nulls, strict=True) if n]
        if count and with_nulls:
            lines.append(f"  NULL: {', '.join(with_nulls)}")
    return lines


def aerobic_lines(root: Path | None = None) -> list[str]:
    trend = aerobic_trend("all", root=root)
    runs, weeks = trend["runs"], trend["weeks"]
    with_temp = sum(r["temperature_c"] is not None for r in runs)
    weeks_with_temp = sum(w["temperature_c"] is not None for w in weeks)
    hot_week_c = trend["method"]["params"]["hot_week_c"]
    return [
        f"aerobic: {len(runs)} valid road runs, {with_temp} with air temperature",
        f"  weeks: {len(weeks)}, {weeks_with_temp} with air temperature,"
        f" {sum(w['hot'] for w in weeks)} hot (>= {hot_week_c:g} °C)",
    ]


def summary(root: Path | None = None) -> str:
    path = analysis_db_path(root)
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        lines = [f"schema version {version}", *table_lines(conn)]
    finally:
        conn.close()
    return "\n".join([*lines, *aerobic_lines(root)])


def main() -> int:
    root = data_dir()
    if not analysis_db_path(root).is_file():
        print("no analysis database yet (run `runsync rebuild`)", file=sys.stderr)
        return 1
    # A Windows pipe defaults to the ANSI code page, which garbles "°C".
    sys.stdout.reconfigure(encoding="utf-8")
    print(summary(root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
