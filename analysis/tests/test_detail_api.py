"""Seam 3: the activity detail, GET /api/activities/{activity_id} (summary).

One activity at a glance: distance, duration, running pace (walking left
out) with Garmin's average pace as reference, average and max HR, cadence
(spm, running seconds only), elevation gain and air temperature. An unknown
id is a 404 with a Chinese message; a non-running activity opens with the
running-only fields null and the reason "仅跑步类活动".
"""

import pytest
from synthetic import insert_activity
from synthetic_aerobic import add_hourly_weather, add_hr_run, steady

# 07:00 NZDT on 2026-10-20 is 18:00Z on the 19th.
START_LOCAL = "2026-10-20T07:00:00"


def get_detail(client_factory, activity_id: int) -> dict:
    r = client_factory().get(f"/api/activities/{activity_id}")
    assert r.status_code == 200, r.text
    return r.json()


def test_summary_of_a_run_with_a_cool_down_walk(analysis_db, client_factory):
    # 20 min at 3.0 m/s, 150 bpm, 170 spm; then 5 min walking at 1.4 m/s,
    # 120 bpm, 110 spm. Garmin's overall pace is 1500 s / 4.02 km = 373.1 s/km;
    # the running pace is 1200 s / 3.6 km = 333.3 s/km.
    add_hr_run(
        analysis_db,
        7,
        START_LOCAL,
        [steady(1200, hr=150.0), steady(300, speed=1.4, hr=120.0, cadence=55.0)],
    )
    analysis_db.execute(
        "UPDATE activities SET activity_name = '晨跑', elevation_gain_m = 42.0,"
        " avg_hr_bpm = NULL, max_hr_bpm = NULL WHERE activity_id = 7"
    )
    analysis_db.commit()
    # Midpoint 18:12:30Z: 12.0 + (14.0 - 12.0) x 750 / 3600.
    add_hourly_weather(analysis_db, {"2026-10-19T18:00:00Z": 12.0, "2026-10-19T19:00:00Z": 14.0})

    body = get_detail(client_factory, 7)

    a = body["activity"]
    assert a["activity_id"] == 7
    assert a["activity_type"] == "running"
    assert a["activity_name"] == "晨跑"
    assert a["start_time_local"] == START_LOCAL
    assert a["is_running"] is True
    s = body["summary"]
    assert s["distance_m"] == pytest.approx(4020.0)
    assert s["duration_s"] == pytest.approx(1500.0)
    assert s["running_pace_s_per_km"] == pytest.approx(333.3, abs=1.0)
    assert s["garmin_pace_s_per_km"] == pytest.approx(373.13, abs=0.1)
    # Time-weighted over the recorded seconds: (1200 x 150 + 300 x 120) / 1500.
    assert s["avg_hr_bpm"] == pytest.approx(144.0)
    assert s["max_hr_bpm"] == pytest.approx(150.0)
    # Running seconds only: the walk's 110 spm stays out, bar the few seconds the
    # 15 s trailing mean still counts as running.
    assert s["avg_cadence_spm"] == pytest.approx(170.0, abs=1.0)
    assert s["elevation_gain_m"] == pytest.approx(42.0)
    assert s["air_temperature_c"] == pytest.approx(12.0 + 2.0 * 750 / 3600)
    assert s["unavailable"] == {}
    assert s["method"]["name"]
    assert "running_types" in s["method"]["params"]


def test_an_unknown_activity_is_a_404_with_a_chinese_message(analysis_db, client_factory):
    insert_activity(analysis_db, 1, START_LOCAL, distance_m=5000, duration_s=1500)

    r = client_factory().get("/api/activities/999")

    assert r.status_code == 404
    assert r.json()["detail"] == "没有编号为 999 的活动。"


def test_a_non_running_activity_has_the_running_fields_null_with_the_reason(
    analysis_db, client_factory
):
    add_hr_run(analysis_db, 3, START_LOCAL, [steady(1800, speed=7.0, hr=130.0)], "cycling")

    body = get_detail(client_factory, 3)

    assert body["activity"]["is_running"] is False
    s = body["summary"]
    assert s["running_pace_s_per_km"] is None
    assert s["garmin_pace_s_per_km"] is None
    assert s["avg_cadence_spm"] is None
    assert s["unavailable"] == {
        "running_pace_s_per_km": "仅跑步类活动",
        "garmin_pace_s_per_km": "仅跑步类活动",
        "avg_cadence_spm": "仅跑步类活动",
        "avg_stride_m": "仅跑步类活动",
    }
    # The rest of the summary is there as for a run.
    assert s["distance_m"] == pytest.approx(12600.0)
    assert s["duration_s"] == pytest.approx(1800.0)
    assert s["avg_hr_bpm"] == pytest.approx(130.0)
    assert s["max_hr_bpm"] == pytest.approx(130.0)


def test_a_run_without_records_falls_back_to_the_garmin_totals(analysis_db, client_factory):
    insert_activity(
        analysis_db,
        4,
        START_LOCAL,
        "treadmill_running",
        distance_m=6000,
        duration_s=1800,
        avg_hr_bpm=148.0,
    )
    analysis_db.execute("UPDATE activities SET max_hr_bpm = 171.0 WHERE activity_id = 4")
    analysis_db.commit()

    s = get_detail(client_factory, 4)["summary"]

    assert s["running_pace_s_per_km"] == pytest.approx(300.0)
    assert s["garmin_pace_s_per_km"] == pytest.approx(300.0)
    assert s["avg_hr_bpm"] == pytest.approx(148.0)
    assert s["max_hr_bpm"] == pytest.approx(171.0)
    assert s["avg_cadence_spm"] is None
    assert s["elevation_gain_m"] is None
    assert s["air_temperature_c"] is None
    assert s["unavailable"] == {}


def test_without_an_analysis_database_every_id_is_a_404(data_dir, client_factory):
    r = client_factory().get("/api/activities/1")

    assert r.status_code == 404
    assert r.json()["detail"] == "没有编号为 1 的活动。"


def test_the_average_stride_is_running_distance_over_steps(analysis_db, client_factory):
    # 3.0 m/s at 170 spm: 3.0 x 60 / 170 = 1.059 m per step. The walk at the
    # end (1.0 m/s, 110 spm) is left out.
    add_hr_run(analysis_db, 4, START_LOCAL, [steady(1200), steady(300, speed=1.0, cadence=55.0)])

    s = get_detail(client_factory, 4)["summary"]

    assert s["avg_stride_m"] == pytest.approx(1.059, abs=0.01)
