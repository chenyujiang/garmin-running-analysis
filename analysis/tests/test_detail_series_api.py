"""Seam 3: the per-second series of the activity detail,
GET /api/activities/{activity_id} -> `series`.

HR, pace, GAP pace, altitude and cadence on one time axis (seconds from the
first sample), downsampled to at most 1500 points: equal time buckets, the
mean inside each, and no bucket spans a pause. Pauses, walking stretches and
steady-state seconds come back as `[start_s, end_s]` intervals.
"""

import pytest
from synthetic import insert_activity
from synthetic_aerobic import add_hr_run, add_paused_hr_run, steady

START_LOCAL = "2026-10-20T07:00:00"


def get_series(client_factory, activity_id: int) -> dict:
    r = client_factory().get(f"/api/activities/{activity_id}")
    assert r.status_code == 200, r.text
    return r.json()["series"]


def test_a_two_hour_run_is_downsampled_to_at_most_1500_points(analysis_db, client_factory):
    # 7200 s at 3.0 m/s (333.3 s/km), 150 bpm, 170 spm, flat.
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(7200, hr=150.0)])

    s = get_series(client_factory, 1)

    n = len(s["t_s"])
    assert 1000 < n <= 1500
    for key in (
        "hr_bpm",
        "pace_s_per_km",
        "gap_pace_s_per_km",
        "altitude_m",
        "cadence_spm",
        "stride_m",
    ):
        assert len(s[key]) == n, key
    assert s["t_s"] == sorted(s["t_s"])
    assert s["t_s"][0] >= 0 and s["t_s"][-1] <= 7200
    assert s["duration_s"] == pytest.approx(7200)
    assert all(v == pytest.approx(150.0) for v in s["hr_bpm"])
    assert all(v == pytest.approx(333.3, abs=0.1) for v in s["pace_s_per_km"])
    # Flat: GAP pace equals pace once the 30 s smoothing has filled.
    assert s["gap_pace_s_per_km"][-1] == pytest.approx(333.3, abs=0.1)
    assert all(v == pytest.approx(170.0) for v in s["cadence_spm"])
    # Stride = speed x 60 / spm.
    assert s["stride_m"][-1] == pytest.approx(1.06, abs=0.01)
    assert all(v == pytest.approx(100.0) for v in s["altitude_m"])
    assert s["unavailable"] == {}
    assert s["method"]["params"]["max_points"] == 1500


def test_no_bucket_spans_a_pause(analysis_db, client_factory):
    # 10500 s at 140 bpm, an 11 s pause, then 10500 s at 160 bpm. Buckets are
    # 15 s wide; counted from the first sample, the bucket [10500, 10515) would
    # hold the last sample before the pause and the first one after it.
    add_paused_hr_run(
        analysis_db, 2, START_LOCAL, [steady(10500, hr=140.0), 11, steady(10500, hr=160.0)]
    )

    s = get_series(client_factory, 2)

    assert len(s["t_s"]) <= 1500
    assert s["bucket_s"] == 15
    assert s["intervals"]["pause"] == [[10500.0, 10511.0]]
    # A bucket mixing both sides would read between 140 and 160.
    assert set(s["hr_bpm"]) == {140.0, 160.0}
    for t, hr in zip(s["t_s"], s["hr_bpm"], strict=True):
        assert not 10500 < t < 10511
        assert hr == (140.0 if t <= 10500 else 160.0)


def test_more_pauses_than_points_still_stay_within_1500_points(analysis_db, client_factory):
    # 2000 stretches of 5 s, each followed by an 11 s pause: 2000 pause-free
    # stretches, more than the 1500-point cap even at one bucket each.
    parts: list = []
    for _ in range(2000):
        parts += [steady(5, hr=150.0), 11]
    add_paused_hr_run(analysis_db, 10, START_LOCAL, parts[:-1])

    s = get_series(client_factory, 10)

    n = len(s["t_s"])
    assert 0 < n <= 1500
    assert len(s["hr_bpm"]) == n
    assert s["t_s"] == sorted(s["t_s"])
    assert set(s["hr_bpm"]) == {150.0}
    assert len(s["intervals"]["pause"]) == 1999


def test_walking_and_steady_seconds_come_back_as_intervals(analysis_db, client_factory):
    # 1800 s steady at the reference HR (145), 300 s walking, 600 s running.
    add_hr_run(
        analysis_db,
        3,
        START_LOCAL,
        [steady(1800), steady(300, speed=1.4, hr=120.0, cadence=55.0), steady(600)],
    )

    iv = get_series(client_factory, 3)["intervals"]

    assert iv["pause"] == []
    # The 10 s trailing cadence mean moves each edge 5 s late: the 6th walking
    # sample (t = 1806) owns 1805-1806; the 5th running one (2105) is running.
    assert iv["walking"] == [[1805.0, 2104.0]]
    # Steady from the end of the 10-minute warm-up until the speed starts to
    # drop (2 s into the walk, within 5% over 60 s). After the walk it comes
    # back once the 30 s mean speed has held 3.0 m/s for most of 60 s.
    assert iv["steady"] == [[600.0, 1802.0], [2186.0, 2700.0]]


def test_without_heart_rate_the_hr_series_is_empty_and_says_why(analysis_db, client_factory):
    add_hr_run(analysis_db, 4, START_LOCAL, [steady(1800, hr=None)])

    s = get_series(client_factory, 4)

    assert s["hr_bpm"] == []
    assert s["unavailable"] == {"hr_bpm": "没有心率记录", "steady": "没有心率记录"}
    assert s["intervals"]["steady"] == []
    # The rest of the run is still there.
    assert len(s["pace_s_per_km"]) == len(s["t_s"]) > 0
    assert s["intervals"]["walking"] == []


def test_a_non_running_activity_has_hr_and_altitude_only(analysis_db, client_factory):
    add_hr_run(analysis_db, 5, START_LOCAL, [steady(1800, speed=7.0, hr=130.0)], "cycling")

    s = get_series(client_factory, 5)

    assert len(s["hr_bpm"]) == len(s["altitude_m"]) == len(s["t_s"]) > 0
    assert set(s["hr_bpm"]) == {130.0}
    for key in ("pace_s_per_km", "gap_pace_s_per_km", "cadence_spm", "stride_m"):
        assert s[key] is None
        assert s["unavailable"][key] == "仅跑步类活动"
    assert s["intervals"]["walking"] is None
    assert s["intervals"]["steady"] is None
    assert s["unavailable"]["walking"] == s["unavailable"]["steady"] == "仅跑步类活动"


def test_gap_pace_is_faster_uphill_and_equals_pace_without_altitude(analysis_db, client_factory):
    # 10 % up at 2.5 m/s (400 s/km). Minetti: Cr(0.1) = 0.0016 - 0.0030 - 0.0433
    # + 0.463 + 1.95 + 3.6 = 5.968 J/kg/m against 3.6 flat, so the flat-ground
    # speed is 2.5 x 1.658 = 4.145 m/s, 241.3 s/km.
    add_hr_run(analysis_db, 6, START_LOCAL, [steady(1200, speed=2.5, grade=0.1)])
    add_hr_run(analysis_db, 8, START_LOCAL, [steady(1200, speed=2.5, grade=0.1)], altitude=False)

    hill = get_series(client_factory, 6)
    flat = get_series(client_factory, 8)

    assert hill["pace_s_per_km"][-1] == pytest.approx(400.0)
    assert hill["gap_pace_s_per_km"][-1] == pytest.approx(241.3, abs=0.2)
    assert flat["altitude_m"] == []
    assert flat["unavailable"] == {"altitude_m": "没有海拔记录"}
    assert flat["gap_pace_s_per_km"][-1] == pytest.approx(400.0)


def test_a_run_without_records_has_empty_series_and_says_why(analysis_db, client_factory):
    insert_activity(
        analysis_db, 9, START_LOCAL, "treadmill_running", distance_m=6000, duration_s=1800
    )

    s = get_series(client_factory, 9)

    assert s["t_s"] == [] and s["hr_bpm"] == [] and s["pace_s_per_km"] == []
    assert s["intervals"] == {"pause": [], "walking": [], "steady": []}
    assert set(s["unavailable"].values()) == {"没有逐秒记录"}
    assert "hr_bpm" in s["unavailable"] and "steady" in s["unavailable"]
