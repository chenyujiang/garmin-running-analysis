"""Seam 3: the splits section of GET /api/activities/{activity_id}.

Two tables: the watch laps as recorded (`laps`, single-foot cadence doubled
to spm), and per-kilometre splits cut on `records.distance`, the last short
split listed on its own with its distance. Each kilometre gives the running
pace (walking left out), GAP pace, average HR, average spm and the altitude
gained and lost. A non-running activity has no kilometre splits (null with
the reason); an activity without laps has an empty lap table and a note.
"""

import pytest
from synthetic import insert_activity
from synthetic_aerobic import add_hr_run, steady
from synthetic_laps import Lap, add_laps

START_LOCAL = "2026-10-20T07:00:00"


def get_splits(client_factory, activity_id: int) -> dict:
    r = client_factory().get(f"/api/activities/{activity_id}")
    assert r.status_code == 200, r.text
    return r.json()["splits"]


def test_a_3300_m_run_has_three_full_kilometres_and_a_300_m_last_split(analysis_db, client_factory):
    # 1100 s at 3.0 m/s = 3300 m.
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(1100)])

    km = get_splits(client_factory, 1)["kilometres"]

    assert [k["distance_m"] for k in km] == pytest.approx([1000.0, 1000.0, 1000.0, 300.0])
    assert [k["partial"] for k in km] == [False, False, False, True]
    assert [k["km"] for k in km] == [1, 2, 3, 4]
    # 3.0 m/s is 333.3 s/km on the flat; GAP pace equals it.
    for k in km:
        assert k["running_pace_s_per_km"] == pytest.approx(333.3, abs=0.5)
        assert k["gap_pace_s_per_km"] == pytest.approx(333.3, abs=0.5)
        assert k["avg_hr_bpm"] == pytest.approx(145.0)
        assert k["avg_cadence_spm"] == pytest.approx(170.0)
        # 3.0 m/s at 170 spm: 1.059 m per step.
        assert k["avg_stride_m"] == pytest.approx(1.059, abs=0.001)


def test_a_kilometre_with_a_walk_has_its_running_pace_without_the_walk(analysis_db, client_factory):
    # km 1: 600 m running at 3.0 m/s, 200 m walking at 1.0 m/s (110 spm), then
    # 200 m running (and 700 m more in km 2). The whole kilometre takes about
    # 467 s; the running pace is 267 s / 800 m = 333.75 s/km.
    add_hr_run(
        analysis_db,
        2,
        START_LOCAL,
        [steady(200), steady(200, speed=1.0, hr=120.0, cadence=55.0), steady(300)],
    )

    km = get_splits(client_factory, 2)["kilometres"]

    assert [k["distance_m"] for k in km] == pytest.approx([1000.0, 700.0])
    assert km[0]["duration_s"] == pytest.approx(467.0, abs=1.0)
    # A few seconds at the start of the walk still count as running (the
    # cadence is a trailing mean), hence the margin.
    assert km[0]["running_pace_s_per_km"] == pytest.approx(333.75, abs=8.0)
    assert km[0]["avg_cadence_spm"] == pytest.approx(170.0, abs=5.0)
    assert km[1]["running_pace_s_per_km"] == pytest.approx(333.3, abs=0.5)


def test_hill_kilometres_have_gap_pace_and_altitude_gained_and_lost(analysis_db, client_factory):
    # 2100 m up a 5% grade, then 2100 m down it, all at 3.0 m/s (333.3 s/km).
    add_hr_run(
        analysis_db,
        3,
        START_LOCAL,
        [steady(700, grade=0.05), steady(700, grade=-0.05)],
    )

    km = get_splits(client_factory, 3)["kilometres"]

    assert len(km) == 5
    assert km[-1]["distance_m"] == pytest.approx(200.0)
    up, down = km[1], km[3]  # well clear of the turn and the start
    assert up["running_pace_s_per_km"] == pytest.approx(333.3, abs=0.5)
    # Minetti: Cr(0.05) / Cr(0) = 1.3015, Cr(-0.05) / Cr(0) = 0.7628.
    assert up["gap_pace_s_per_km"] == pytest.approx(256.1, abs=1.0)
    assert down["gap_pace_s_per_km"] == pytest.approx(437.0, abs=1.0)
    # A kilometre's samples are the 3 m steps that start in it, so altitude
    # can be one step (0.15 m) off.
    assert up["elevation_gain_m"] == pytest.approx(50.0, abs=0.2)
    assert up["elevation_loss_m"] == pytest.approx(0.0)
    assert down["elevation_gain_m"] == pytest.approx(0.0)
    assert down["elevation_loss_m"] == pytest.approx(50.0, abs=0.2)
    # km 3 climbs 100 m to the top and descends 900 m.
    assert km[2]["elevation_gain_m"] == pytest.approx(5.0, abs=0.2)
    assert km[2]["elevation_loss_m"] == pytest.approx(45.0, abs=0.2)


def test_the_watch_laps_come_with_cadence_doubled_to_spm(analysis_db, client_factory):
    add_hr_run(analysis_db, 4, START_LOCAL, [steady(600)])
    add_laps(
        analysis_db,
        4,
        [
            Lap(
                1000.0,
                300.0,
                avg_hr_bpm=150.0,
                max_hr_bpm=158.0,
                avg_cadence=88.0,
                elevation_gain_m=4.0,
                elevation_loss_m=1.0,
                elapsed_duration_s=330.0,
            ),
            Lap(800.0, 300.0, avg_hr_bpm=140.0, avg_cadence=84.5),
        ],
    )

    s = get_splits(client_factory, 4)

    laps = s["laps"]
    assert [lap["lap"] for lap in laps] == [1, 2]
    assert [lap["avg_cadence_spm"] for lap in laps] == pytest.approx([176.0, 169.0])
    # Stride = speed x 60 / spm: 3.333 m/s at 176 spm, 2.667 m/s at 169 spm.
    assert [lap["avg_stride_m"] for lap in laps] == pytest.approx([1.136, 0.947], abs=0.001)
    first = laps[0]
    assert first["distance_m"] == pytest.approx(1000.0)
    # Timer time, not elapsed: the 30 s stood still at a light are left out.
    assert first["duration_s"] == pytest.approx(300.0)
    assert first["pace_s_per_km"] == pytest.approx(300.0)
    assert first["avg_hr_bpm"] == pytest.approx(150.0)
    assert first["max_hr_bpm"] == pytest.approx(158.0)
    assert first["elevation_gain_m"] == pytest.approx(4.0)
    assert first["elevation_loss_m"] == pytest.approx(1.0)
    assert laps[1]["pace_s_per_km"] == pytest.approx(375.0)
    assert "laps" not in s["unavailable"]
    assert s["method"]["name"]


def test_without_laps_the_lap_table_is_empty_with_a_note(analysis_db, client_factory):
    add_hr_run(analysis_db, 5, START_LOCAL, [steady(600)])

    s = get_splits(client_factory, 5)

    assert s["laps"] == []
    assert s["unavailable"] == {"laps": "手表没有记录圈"}
    assert len(s["kilometres"]) == 2


def test_a_remainder_under_10_m_after_the_last_kilometre_is_not_listed(analysis_db, client_factory):
    # 1002 m: one kilometre and 2 m.
    add_hr_run(analysis_db, 6, START_LOCAL, [steady(334)])

    km = get_splits(client_factory, 6)["kilometres"]

    assert [k["distance_m"] for k in km] == pytest.approx([1000.0])
    assert km[0]["partial"] is False


def test_a_non_running_activity_has_no_kilometre_splits(analysis_db, client_factory):
    add_hr_run(analysis_db, 7, START_LOCAL, [steady(1800, speed=7.0, hr=130.0)], "cycling")
    add_laps(analysis_db, 7, [Lap(12600.0, 1800.0, avg_hr_bpm=130.0, avg_cadence=80.0)])

    s = get_splits(client_factory, 7)

    assert s["kilometres"] is None
    assert s["unavailable"] == {"kilometres": "仅跑步类活动"}
    # The laps are there, but a cycling cadence (rpm) is not spm and a pace
    # means nothing on a bike.
    (lap,) = s["laps"]
    assert lap["distance_m"] == pytest.approx(12600.0)
    assert lap["avg_hr_bpm"] == pytest.approx(130.0)
    assert lap["avg_cadence_spm"] is None
    assert lap["pace_s_per_km"] is None


def test_a_run_without_records_has_no_kilometre_splits_with_the_reason(analysis_db, client_factory):
    insert_activity(
        analysis_db, 8, START_LOCAL, "treadmill_running", distance_m=6000, duration_s=1800
    )

    s = get_splits(client_factory, 8)

    assert s["kilometres"] is None
    assert s["unavailable"] == {"laps": "手表没有记录圈", "kilometres": "没有逐秒距离记录"}


def test_the_altitude_drop_while_the_altimeter_settles_is_left_out(analysis_db, client_factory):
    # A flat run whose altimeter reads 36 m too high at the start and settles
    # within 40 s (as after a car ride): without the settling rule km 1 shows
    # 36 m lost and a GAP pace well off the running pace.
    add_hr_run(analysis_db, 7, START_LOCAL, [steady(40, grade=-0.3), steady(1000)])

    km = get_splits(client_factory, 7)["kilometres"]

    first = km[0]
    assert first["gap_pace_s_per_km"] == pytest.approx(first["running_pace_s_per_km"], abs=0.5)
    assert first["elevation_loss_m"] == pytest.approx(0.0)
    assert first["elevation_gain_m"] == pytest.approx(0.0)
