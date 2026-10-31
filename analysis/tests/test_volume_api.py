"""Seam 3: the weekly-volume endpoint, GET /api/volume.

`today` is passed as a query parameter so the week boundaries are fixed.
2026-10-28 is a Wednesday: this week starts Mon 2026-10-26, last week 2026-10-19.
"""

import pytest
from synthetic import add_run, insert_activity, pause, run, stop, walk

TODAY = "2026-10-28"


def get_volume(client_factory, today: str = TODAY) -> dict:
    r = client_factory().get("/api/volume", params={"today": today})
    assert r.status_code == 200
    return r.json()


def test_a_plain_run_this_week_counts_its_full_distance(analysis_db, client_factory):
    add_run(analysis_db, 1, "2026-10-27T07:00:00", [run(1200)])

    body = get_volume(client_factory)

    assert body["this_week"]["week_start"] == "2026-10-26"
    assert body["this_week"]["distance_m"] == pytest.approx(3600.0)
    assert body["this_week"]["runs"] == 1


def only_run(body: dict, activity_id: int) -> dict:
    [r] = [r for r in body["runs"] if r["activity_id"] == activity_id]
    return r


def test_walking_after_the_run_does_not_slow_the_running_pace(analysis_db, client_factory):
    # 20 min at 5:33/km, then a 5 min cool-down walk. Garmin's overall pace is
    # (1500 s) / (3600 + 420 m) = 373.1 s/km; the running pace stays ~333 s/km.
    add_run(analysis_db, 1, "2026-10-27T07:00:00", [run(1200), walk(300)])

    body = get_volume(client_factory)
    r = only_run(body, 1)

    assert r["source"] == "records"
    assert r["garmin_pace_s_per_km"] == pytest.approx(373.13, abs=0.01)
    assert r["run_pace_s_per_km"] == pytest.approx(333.3, abs=1.0)
    assert r["run_distance_m"] == pytest.approx(3600, abs=10)
    assert body["this_week"]["distance_m"] == pytest.approx(3600, abs=10)


def test_a_walk_break_in_the_middle_is_left_out(analysis_db, client_factory):
    # 10 min run, 2 min walk, 10 min run. With a 10 s trailing mean, the first
    # 5 walking seconds still read as running and the first 4 running seconds
    # after the break read as walking: 1201 s and 3595 m of running.
    add_run(analysis_db, 1, "2026-10-27T07:00:00", [run(600), walk(120), run(600)])

    r = only_run(get_volume(client_factory), 1)

    assert r["run_duration_s"] == pytest.approx(1201)
    assert r["run_distance_m"] == pytest.approx(3595)
    assert r["run_pace_s_per_km"] == pytest.approx(334.1, abs=0.1)


def test_a_stop_shorter_than_ten_seconds_still_counts_as_running(analysis_db, client_factory):
    # An 8 s stop at a crossing stays inside the run: 1208 s for 3600 m.
    add_run(analysis_db, 1, "2026-10-27T07:00:00", [run(600), stop(8), run(600)])

    r = only_run(get_volume(client_factory), 1)

    assert r["run_duration_s"] == pytest.approx(1208)
    assert r["run_distance_m"] == pytest.approx(3600)
    assert r["run_pace_s_per_km"] == pytest.approx(335.6, abs=0.1)


def test_a_paused_watch_adds_neither_time_nor_distance(analysis_db, client_factory):
    # 10 min run, watch paused 5 min (no samples), 10 min run: 1200 s, 3600 m.
    add_run(analysis_db, 1, "2026-10-27T07:00:00", [run(600), pause(300), run(600)])

    r = only_run(get_volume(client_factory), 1)

    assert r["run_duration_s"] == pytest.approx(1200)
    assert r["run_distance_m"] == pytest.approx(3600)


def test_weeks_follow_local_start_time_and_an_activity_crossing_midnight_stays_in_its_week(
    analysis_db, client_factory
):
    # Sunday 23:50 local, 20 min: ends on Monday, counts entirely in last week.
    add_run(analysis_db, 1, "2026-10-25T23:50:00", [run(1200)])
    # Monday 06:00 local is still Sunday in UTC; it belongs to this week.
    add_run(analysis_db, 2, "2026-10-26T06:00:00", [run(600)])
    add_run(analysis_db, 3, "2026-10-19T07:00:00", [run(1000)])

    body = get_volume(client_factory)

    assert body["this_week"] == {
        "week_start": "2026-10-26",
        "distance_m": pytest.approx(1800),
        "runs": 1,
        "complete": False,
    }
    assert body["last_week"] == {
        "week_start": "2026-10-19",
        "distance_m": pytest.approx(6600),
        "runs": 2,
        "complete": True,
    }


def test_treadmill_and_trail_runs_count_but_other_sports_do_not(analysis_db, client_factory):
    add_run(analysis_db, 1, "2026-10-26T07:00:00", [run(1000)], activity_type="treadmill_running")
    add_run(analysis_db, 2, "2026-10-27T07:00:00", [run(500)], activity_type="trail_running")
    add_run(analysis_db, 3, "2026-10-27T18:00:00", [run(2000)], activity_type="cycling")
    insert_activity(
        analysis_db, 4, "2026-10-28T07:00:00", "walking", distance_m=4000.0, duration_s=3000.0
    )

    body = get_volume(client_factory)

    assert body["this_week"]["distance_m"] == pytest.approx(4500)
    assert body["this_week"]["runs"] == 2
    assert {r["activity_id"] for r in body["runs"]} == {1, 2}


def test_rolling_seven_days_is_today_and_the_six_days_before(analysis_db, client_factory):
    add_run(analysis_db, 1, "2026-10-21T19:00:00", [run(1000)])  # 7 days ago: out
    add_run(analysis_db, 2, "2026-10-22T07:00:00", [run(600)])  # 6 days ago: in
    add_run(analysis_db, 3, "2026-10-28T07:00:00", [run(400)])  # today: in
    add_run(analysis_db, 4, "2026-10-29T07:00:00", [run(800)])  # after today: ignored

    body = get_volume(client_factory)

    assert body["rolling_7d"] == {
        "start": "2026-10-22",
        "end": "2026-10-28",
        "distance_m": pytest.approx(3000),
        "runs": 2,
    }
    assert body["this_week"]["distance_m"] == pytest.approx(1200)


def test_twelve_weeks_oldest_first_with_empty_weeks_and_this_week_unfinished(
    analysis_db, client_factory
):
    add_run(analysis_db, 1, "2026-08-10T07:00:00", [run(1000)])  # first week of the window
    add_run(analysis_db, 2, "2026-08-09T07:00:00", [run(1000)])  # the Sunday before: outside
    add_run(analysis_db, 3, "2026-09-16T07:00:00", [run(2000)])

    weeks = get_volume(client_factory)["weeks"]

    assert len(weeks) == 12
    assert weeks[0] == {
        "week_start": "2026-08-10",
        "distance_m": pytest.approx(3000),
        "runs": 1,
        "complete": True,
    }
    assert weeks[5]["week_start"] == "2026-09-14"
    assert weeks[5]["distance_m"] == pytest.approx(6000)
    assert weeks[1] == {"week_start": "2026-08-17", "distance_m": 0.0, "runs": 0, "complete": True}
    assert weeks[-1]["week_start"] == "2026-10-26"
    assert weeks[-1]["complete"] is False
    assert [w["complete"] for w in weeks].count(False) == 1


def test_a_run_without_cadence_falls_back_to_the_garmin_totals(analysis_db, client_factory):
    insert_activity(
        analysis_db, 1, "2026-10-27T07:00:00", "running", distance_m=5000.0, duration_s=1500.0
    )

    body = get_volume(client_factory)
    r = only_run(body, 1)

    assert r["source"] == "activity"
    assert r["run_distance_m"] == pytest.approx(5000)
    assert r["run_pace_s_per_km"] == pytest.approx(300)
    assert body["this_week"]["distance_m"] == pytest.approx(5000)
    # The page says how many runs in the 12 weeks used Garmin's totals.
    assert body["garmin_totals_runs"] == 1


def test_runs_with_cadence_are_not_counted_as_using_garmin_totals(analysis_db, client_factory):
    add_run(analysis_db, 1, "2026-10-27T07:00:00", [run(600)])

    assert get_volume(client_factory)["garmin_totals_runs"] == 0


def test_the_cadence_threshold_comes_from_config(data_dir, analysis_db, client_factory):
    with (data_dir / "config.toml").open("a", encoding="utf-8") as f:
        f.write("\n[run_walk]\ncadence_spm = 175\n")
    # 170 spm is running by default, walking at a 175 spm threshold.
    add_run(analysis_db, 1, "2026-10-27T07:00:00", [run(1200)])

    body = get_volume(client_factory)

    assert body["this_week"]["distance_m"] == 0
    assert body["method"]["params"]["cadence_spm"] == 175


def test_the_method_note_carries_the_parameters(analysis_db, client_factory):
    method = get_volume(client_factory)["method"]

    assert method["params"]["cadence_spm"] == 140
    assert method["params"]["smoothing_s"] == 10
    assert method["params"]["min_walk_s"] == 10
    assert "treadmill_running" in method["params"]["activity_types"]
    assert "140 spm" in method["description"]


def test_a_gap_over_ten_seconds_is_a_pause_by_default(analysis_db, client_factory):
    # 10 min run, 20 s without samples, 10 min run: the gap is a pause.
    add_run(analysis_db, 1, "2026-10-27T07:00:00", [run(600), pause(20), run(600)])

    body = get_volume(client_factory)

    assert only_run(body, 1)["run_duration_s"] == pytest.approx(1200)
    assert body["method"]["params"]["pause_gap_s"] == 10


def test_pause_gap_s_from_config_overrides_the_default(data_dir, analysis_db, client_factory):
    with (data_dir / "config.toml").open("a", encoding="utf-8") as f:
        f.write("\n[run_walk]\npause_gap_s = 30\n")
    add_run(analysis_db, 1, "2026-10-27T07:00:00", [run(600), pause(20), run(600)])

    body = get_volume(client_factory)

    assert only_run(body, 1)["run_duration_s"] == pytest.approx(1220)
    assert body["method"]["params"]["pause_gap_s"] == 30


def test_without_an_analysis_database_everything_is_zero(data_dir, client_factory):
    body = get_volume(client_factory)

    assert body["has_data"] is False
    assert body["this_week"]["distance_m"] == 0
    assert body["rolling_7d"]["runs"] == 0
    assert len(body["weeks"]) == 12
    assert body["runs"] == []


def test_an_empty_analysis_database_reports_no_data(analysis_db, client_factory):
    body = get_volume(client_factory)

    assert body["has_data"] is False
    assert all(w["distance_m"] == 0 for w in body["weeks"])


def test_today_defaults_to_the_current_date(analysis_db, client_factory):
    from datetime import date

    body = client_factory().get("/api/volume").json()

    assert body["today"] == date.today().isoformat()
