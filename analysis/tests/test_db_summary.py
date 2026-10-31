"""scripts/db_summary.py: aggregate numbers only, never a coordinate."""

import importlib.util
from pathlib import Path

from synthetic_aerobic import add_hourly_weather, add_hr_run, steady, utc_hours

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "db_summary.py"
_spec = importlib.util.spec_from_file_location("db_summary", SCRIPT)
db_summary = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(db_summary)


def run_in_air(conn, activity_id: int, day: str, air_c: float) -> None:
    start_utc = add_hr_run(conn, activity_id, f"{day}T07:00:00", [steady(1800)])
    add_hourly_weather(conn, utc_hours(start_utc, [air_c, air_c]))


def test_the_summary_counts_rows_ranges_runs_and_hot_weeks(data_dir, analysis_db):
    run_in_air(analysis_db, 1, "2026-10-13", 25.0)
    run_in_air(analysis_db, 2, "2026-10-14", 25.0)
    run_in_air(analysis_db, 3, "2026-10-20", 10.0)

    out = db_summary.summary(data_dir)

    assert "activities: 3 rows" in out
    assert "  start_time_local: 2026-10-13T07:00:00 .. 2026-10-20T07:00:00" in out
    assert "hourly_weather: 6 rows" in out
    assert "aerobic: 3 valid road runs, 3 with air temperature" in out
    assert "1 hot (>= 22 °C)" in out


def test_the_summary_prints_no_coordinates(data_dir, analysis_db):
    run_in_air(analysis_db, 1, "2026-10-13", 25.0)

    out = db_summary.summary(data_dir)

    # POSITION (10.02, 20.03) and GRID (10.0, 20.0) from synthetic_aerobic.
    for value in ("10.02", "20.03", "10.0", "20.0"):
        assert value not in out


def test_the_summary_reports_null_counts(data_dir, analysis_db):
    add_hr_run(analysis_db, 1, "2026-10-13T07:00:00", [steady(1800)], gps=False)

    out = db_summary.summary(data_dir)

    assert "lat=1801" in out and "lon=1801" in out


def test_without_a_database_it_says_so_and_fails(data_dir, capsys):
    assert db_summary.main() == 1
    assert "no analysis database yet" in capsys.readouterr().err
