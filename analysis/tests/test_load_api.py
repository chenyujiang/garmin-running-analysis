"""Seam 3: the dashboard's training-load endpoint, GET /api/load.

Config (conftest): HRmax 192, HRrest 55 from 2021-08-01. One hour at HRmax is
60 · 0.64 · e^1.92 = 261.92 TRIMP. Expected CTL/ATL values are the
formulas.md 1/N vectors for daily load 100 scaled by 2.6192.
"""

from datetime import date, timedelta

import pytest
from synthetic_hr import insert_activity, insert_run

HOUR_AT_MAX = 261.9248


def get_load(client_factory, today: str) -> dict:
    r = client_factory().get("/api/load", params={"today": today})
    assert r.status_code == 200
    return r.json()


def day(body: dict, iso: str) -> dict:
    return next(p for p in body["series"] if p["date"] == iso)


def test_one_hour_at_hr_max_loads_ctl_and_atl_by_one_over_n(analysis_db, client_factory):
    insert_run(analysis_db, 1, "2026-10-01", heart_rate=192)

    body = get_load(client_factory, "2026-10-02")

    d1 = day(body, "2026-10-01")
    assert d1["trimp"] == pytest.approx(HOUR_AT_MAX, abs=0.01)
    assert d1["ctl"] == pytest.approx(6.2363, abs=0.001)
    assert d1["atl"] == pytest.approx(37.4178, abs=0.001)
    # TSB is yesterday's CTL − ATL, so the training day itself starts at 0.
    assert d1["tsb"] == pytest.approx(0, abs=1e-9)
    assert body["current"]["date"] == "2026-10-02"
    assert body["current"]["tsb"] == pytest.approx(6.2363 - 37.4178, abs=0.001)


def daily_runs(conn, first: date, days: int, start_id: int = 1) -> None:
    for i in range(days):
        insert_run(conn, start_id + i, first + timedelta(days=i), heart_rate=192)


def test_a_week_of_hard_training_from_zero_is_a_load_spike(analysis_db, client_factory):
    daily_runs(analysis_db, date(2026, 10, 1), 7)

    body = get_load(client_factory, "2026-10-07")

    assert body["current"]["ctl"] == pytest.approx(40.6568, abs=0.001)
    assert body["current"]["atl"] == pytest.approx(172.8922, abs=0.001)
    assert body["current"]["ratio"] == pytest.approx(172.8922 / 40.6568, abs=0.001)
    assert body["spike"] is True
    assert body["spike_since"] == "2026-10-01"


def test_rest_days_decay_the_load_and_the_ratio_can_fall_below_the_spike_line(
    analysis_db, client_factory
):
    daily_runs(analysis_db, date(2026, 8, 1), 42)  # Aug 1 .. Sep 11

    after_42 = get_load(client_factory, "2026-09-11")["current"]
    assert after_42["ctl"] == pytest.approx(166.7267, abs=0.001)
    assert after_42["atl"] == pytest.approx(261.5208, abs=0.001)

    body = get_load(client_factory, "2026-09-14")  # three rest days
    assert body["current"]["ctl"] == pytest.approx(155.0989, abs=0.001)
    assert body["current"]["atl"] == pytest.approx(164.6895, abs=0.001)
    assert body["spike"] is False
    assert body["spike_since"] is None


def test_activities_without_heart_rate_are_missing_and_add_no_load(analysis_db, client_factory):
    insert_run(analysis_db, 1, "2026-10-01", heart_rate=192)
    insert_activity(analysis_db, 2, "2026-10-02")  # no FIT records at all
    insert_run(analysis_db, 3, "2026-10-03", heart_rate=None)  # records, no HR

    body = get_load(client_factory, "2026-10-03")

    assert day(body, "2026-10-02")["trimp"] == 0
    assert day(body, "2026-10-03")["trimp"] == 0
    assert body["current"]["ctl"] == pytest.approx(6.2363 * (41 / 42) ** 2, abs=0.001)
    assert body["missing_hr_count"] == 2
    assert [m["activity_id"] for m in body["missing_hr_recent"]] == [2, 3]
    assert {m["reason"] for m in body["missing_hr_recent"]} == {"没有心率"}


def test_every_activity_type_with_heart_rate_counts(analysis_db, client_factory):
    insert_run(analysis_db, 1, "2026-10-01", heart_rate=192, seconds=1800)
    insert_run(
        analysis_db, 2, "2026-10-01", heart_rate=192, seconds=1800, activity_type="cycling", hour=18
    )

    body = get_load(client_factory, "2026-10-01")

    assert day(body, "2026-10-01")["trimp"] == pytest.approx(HOUR_AT_MAX, abs=0.01)


def test_sparse_sampling_counts_the_gap_but_pauses_do_not(analysis_db, client_factory):
    # Smart recording every 5 s: 720 records, the last one counts 1 s.
    insert_run(analysis_db, 1, "2026-10-01", heart_rate=192, every_s=5)
    # 07:00-07:30 at HRmax, paused until 09:30, then 30 more minutes. The pause
    # counts as one capped 10 s gap.
    insert_run(analysis_db, 2, "2026-10-02", heart_rate=192, seconds=3 * 3600)
    analysis_db.execute(
        "DELETE FROM records WHERE activity_id = 2 AND ("
        " (timestamp > '2026-10-02T07:30:00Z' AND timestamp < '2026-10-02T09:30:00Z')"
        " OR timestamp >= '2026-10-02T10:00:00Z')"
    )
    analysis_db.commit()

    body = get_load(client_factory, "2026-10-02")

    assert day(body, "2026-10-01")["trimp"] == pytest.approx(HOUR_AT_MAX * 3596 / 3600, abs=0.01)
    assert day(body, "2026-10-02")["trimp"] == pytest.approx(HOUR_AT_MAX * 3610 / 3600, abs=0.01)


def test_each_activity_uses_the_physiology_in_effect_on_its_date(
    data_dir, analysis_db, client_factory
):
    with (data_dir / "config.toml").open("a", encoding="utf-8") as f:
        f.write(
            "\n[[physiology]]\neffective_from = 2026-06-01\n"
            "hr_max = 180\nhr_rest = 55\nlthr = 165\n"
        )
    insert_run(analysis_db, 1, "2026-05-31", heart_rate=180)
    insert_run(analysis_db, 2, "2026-06-01", heart_rate=180)
    insert_run(analysis_db, 3, "2021-07-31", heart_rate=180)  # before any set

    body = get_load(client_factory, "2026-06-01")

    # x = (180 − 55) / (192 − 55) under the old set; x = 1 under the new one.
    assert day(body, "2026-05-31")["trimp"] == pytest.approx(201.9894, abs=0.01)
    assert day(body, "2026-06-01")["trimp"] == pytest.approx(HOUR_AT_MAX, abs=0.01)
    assert body["missing_hr_count"] == 1
    assert body["method"]["hr_max"] == 180
    assert body["method"]["physiology_effective_from"] == "2026-06-01"


def test_the_series_covers_the_last_12_weeks_including_rest_days(analysis_db, client_factory):
    insert_run(analysis_db, 1, "2026-01-01", heart_rate=192)
    insert_run(analysis_db, 2, "2026-10-01", heart_rate=192)

    body = get_load(client_factory, "2026-10-30")

    dates = [p["date"] for p in body["series"]]
    assert len(dates) == 84
    assert dates[0] == "2026-08-08"
    assert dates[-1] == "2026-10-30"
    assert sum(1 for p in body["series"] if p["trimp"] > 0) == 1


def test_activities_after_today_are_ignored(analysis_db, client_factory):
    insert_run(analysis_db, 1, "2026-10-01", heart_rate=192)
    insert_run(analysis_db, 2, "2026-10-05", heart_rate=192)

    body = get_load(client_factory, "2026-10-02")

    assert body["current"]["ctl"] == pytest.approx(6.2363 * 41 / 42, abs=0.001)


def test_the_method_names_the_formula_and_current_parameters(analysis_db, client_factory):
    insert_run(analysis_db, 1, "2026-10-01", heart_rate=150)

    m = get_load(client_factory, "2026-10-01")["method"]

    assert (m["trimp_a"], m["trimp_b"]) == (0.64, 1.92)
    assert (m["hr_rest"], m["hr_max"]) == (55, 192)
    assert (m["ctl_days"], m["atl_days"], m["spike_ratio"]) == (42, 7, 1.5)
    assert m["recursion"] == "1/N"
    assert "Banister" in m["trimp"]


@pytest.mark.parametrize("make_db", [False, True])
def test_no_database_or_an_empty_one_has_no_load(data_dir, client_factory, make_db, request):
    if make_db:
        request.getfixturevalue("analysis_db")

    body = get_load(client_factory, "2026-10-30")

    assert body["has_data"] is False
    assert body["current"] is None
    assert body["spike"] is False
    assert body["series"] == []
    assert body["method"]["hr_max"] == 192


def test_today_defaults_to_the_real_date(analysis_db, client_factory):
    insert_run(analysis_db, 1, date.today() - timedelta(days=3), heart_rate=192)

    body = client_factory().get("/api/load").json()

    assert body["as_of"] == date.today().isoformat()
    assert body["current"]["date"] == date.today().isoformat()


def test_the_load_read_does_not_modify_the_analysis_database(data_dir, analysis_db, client_factory):
    insert_run(analysis_db, 1, "2026-10-01", heart_rate=192)
    db = data_dir / "running.sqlite"
    before = db.read_bytes()

    get_load(client_factory, "2026-10-02")

    assert db.read_bytes() == before
