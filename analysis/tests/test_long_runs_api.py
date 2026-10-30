"""Seam 3: the long-run table, GET /api/long-runs.

EF = GAP speed in m/min / heart rate, over steady-state seconds. Decoupling
compares EF of the first and second half of the steady time. The first 600 s
of moving time are warm-up and never steady, so a run of T seconds at 1 Hz
has steady seconds t = 601..T.
"""

import pytest
from synthetic import insert_activity
from synthetic_aerobic import add_hr_run, steady

TODAY = "2026-10-28"


def get_long_runs(client_factory, today: str = TODAY, **params) -> dict:
    r = client_factory().get("/api/long-runs", params={"today": today, **params})
    assert r.status_code == 200, r.text
    return r.json()


def by_id(body: dict) -> dict[int, dict]:
    return {r["activity_id"]: r for r in body["runs"]}


def test_a_59_minute_run_is_not_a_long_run(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", [steady(3540, speed=3.0, hr=150)])
    add_hr_run(analysis_db, 2, "2026-10-22T07:00:00", [steady(3600, speed=3.0, hr=150)])

    body = get_long_runs(client_factory)

    assert body["has_data"] is True
    assert list(by_id(body)) == [2]
    run = by_id(body)[2]
    assert run["start_time_local"] == "2026-10-22T07:00:00"
    assert run["distance_m"] == pytest.approx(10800.0)
    assert run["duration_s"] == pytest.approx(3600.0)
    # 180 m/min at 150 bpm.
    assert run["ef"] == pytest.approx(1.2, abs=1e-6)
    assert run["decoupling_pct"] == pytest.approx(0.0, abs=1e-6)
    assert run["decoupling_high"] is False


def drop_records(conn, activity_id: int, first_s: int, last_s: int) -> None:
    """Delete the samples at t = first_s..last_s: a pause long enough that the
    30 s smoothing and the 60 s speed window start fresh after it."""
    rows = conn.execute(
        "SELECT timestamp FROM records WHERE activity_id = ? ORDER BY timestamp", (activity_id,)
    ).fetchall()
    stamps = [r[0] for r in rows[first_s : last_s + 1]]
    conn.executemany(
        "DELETE FROM records WHERE activity_id = ? AND timestamp = ?",
        [(activity_id, s) for s in stamps],
    )
    conn.commit()


def two_halves(conn, activity_id: int, start_local: str, first, second) -> None:
    """Steady t = 601..2100 (1500 s) at `first`, a 90 s pause, then 1500 s of
    steady time at `second` (t = 2192..3691; t = 2191 follows the pause)."""
    add_hr_run(
        conn,
        activity_id,
        start_local,
        [steady(2100, speed=first[0], hr=first[1]), steady(1591, speed=second[0], hr=second[1])],
    )
    drop_records(conn, activity_id, 2101, 2190)


def test_decoupling_above_five_percent_is_flagged(analysis_db, client_factory):
    # formulas.md section 6: 200 m/min at 140 bpm, then 198 m/min at 146 bpm.
    two_halves(analysis_db, 1, "2026-10-25T07:00:00", (200 / 60, 140), (198 / 60, 146))

    run = by_id(get_long_runs(client_factory))[1]

    assert run["ef_first"] == pytest.approx(1.428571, abs=1e-5)
    assert run["ef_second"] == pytest.approx(1.356164, abs=1e-5)
    assert run["decoupling_pct"] == pytest.approx(5.068, abs=1e-3)
    assert run["decoupling_high"] is True
    assert run["ef"] == pytest.approx((200 + 198) / (140 + 146), abs=1e-5)


def test_negative_or_small_decoupling_is_not_flagged(analysis_db, client_factory):
    # Second half faster at the same HR: EF rises, decoupling is negative.
    two_halves(analysis_db, 1, "2026-10-20T07:00:00", (3.0, 150), (3.15, 150))
    # 4% drift: 180 m/min at 144 then at 150 bpm.
    two_halves(analysis_db, 2, "2026-10-22T07:00:00", (3.0, 144), (3.0, 150))

    runs = by_id(get_long_runs(client_factory))

    assert runs[1]["decoupling_pct"] == pytest.approx(-5.0, abs=1e-3)
    assert runs[1]["decoupling_high"] is False
    assert runs[2]["decoupling_pct"] == pytest.approx(4.0, abs=1e-3)
    assert runs[2]["decoupling_high"] is False


def test_newest_first_limited_and_nothing_after_today(analysis_db, client_factory):
    for i, day in enumerate(["2026-10-01", "2026-10-08", "2026-10-15", "2026-10-29"], start=1):
        add_hr_run(analysis_db, i, f"{day}T07:00:00", [steady(3600)])

    body = get_long_runs(client_factory, limit=2)

    assert [r["activity_id"] for r in body["runs"]] == [3, 2]


def test_other_sports_are_not_long_runs(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", [steady(5400)], "cycling")
    add_hr_run(analysis_db, 2, "2026-10-21T07:00:00", [steady(5400)], "walking")
    add_hr_run(analysis_db, 3, "2026-10-22T07:00:00", [steady(3600)], "trail_running")

    assert list(by_id(get_long_runs(client_factory))) == [3]


def test_a_long_run_without_heart_rate_has_no_ef(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", [steady(4200, hr=None)])
    insert_activity(analysis_db, 2, "2026-10-21T07:00:00", distance_m=12000, duration_s=4000)

    runs = by_id(get_long_runs(client_factory))

    for i in (1, 2):
        assert runs[i]["ef"] is None
        assert runs[i]["decoupling_pct"] is None
        assert runs[i]["decoupling_high"] is False
    assert runs[2]["steady_s"] == 0


def test_no_database_means_no_long_runs(data_dir, client_factory):
    body = get_long_runs(client_factory)

    assert body["has_data"] is False
    assert body["runs"] == []
    assert body["method"]["params"]["min_duration_s"] == 3600
    assert body["method"]["params"]["decoupling_limit_pct"] == 5.0
    assert body["method"]["params"]["ef_unit"] == "m/min per bpm"
