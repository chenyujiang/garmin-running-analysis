"""Seam 3: the aerobic-capacity endpoint, GET /api/aerobic.

`today` pins the date. 2026-10-28 is a Wednesday: this week starts Mon
2026-10-26, last week 2026-10-19. A 30 min steady run leaves 20 min after the
10 min warm-up is dropped; the 30 s smoothing and 60 s speed window then
trim a little more, still well above the 10 min minimum.
"""

from datetime import date, timedelta

import pytest
from synthetic_aerobic import add_hourly_weather, add_hr_run, steady, utc_hours

TODAY = "2026-10-28"
FLAT_PACE = 1000 / 3.0  # 333.3 s/km


def get_aerobic(client_factory, range_: str = "6m", today: str = TODAY) -> dict:
    r = client_factory().get("/api/aerobic", params={"range": range_, "today": today})
    assert r.status_code == 200, r.text
    return r.json()


def week(body: dict, monday: str) -> dict:
    [w] = [w for w in body["weeks"] if w["week_start"] == monday]
    return w


def day_after(monday: str, days: int) -> str:
    return (date.fromisoformat(monday) + timedelta(days=days)).isoformat()


def ids(body: dict) -> list[int]:
    return sorted(r["activity_id"] for r in body["runs"])


def test_two_steady_runs_give_the_weekly_median(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", [steady(1800, speed=3.0)])
    add_hr_run(analysis_db, 2, "2026-10-22T07:00:00", [steady(1800, speed=3.2)])

    w = week(get_aerobic(client_factory), "2026-10-19")

    assert w["runs"] == 2
    assert w["speed_mps"] == pytest.approx(3.1, abs=1e-6)
    assert w["pace_s_per_km"] == pytest.approx(1000 / 3.1, abs=0.01)


def test_a_week_with_one_valid_run_stays_empty(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", [steady(1800)])

    body = get_aerobic(client_factory)
    w = week(body, "2026-10-19")

    assert w["runs"] == 1
    assert w["speed_mps"] is None
    assert w["pace_s_per_km"] is None
    assert w["rolling_speed_mps"] is None
    assert ids(body) == [1]
    assert body["runs"][0]["pace_s_per_km"] == pytest.approx(FLAT_PACE, abs=0.01)


def test_treadmill_and_trail_runs_do_not_count(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", [steady(1800)])
    add_hr_run(analysis_db, 2, "2026-10-21T07:00:00", [steady(1800)], "treadmill_running")
    add_hr_run(analysis_db, 3, "2026-10-22T07:00:00", [steady(1800)], "trail_running")

    body = get_aerobic(client_factory)

    assert week(body, "2026-10-19")["runs"] == 1
    assert week(body, "2026-10-19")["speed_mps"] is None
    assert ids(body) == [1]


@pytest.mark.parametrize("missing", ["gps", "altitude"])
def test_a_road_run_without_gps_or_altitude_does_not_count(analysis_db, client_factory, missing):
    # Logged as a road run but recorded like a treadmill: no position or no
    # altitude in the per-second records.
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", [steady(1800)])
    add_hr_run(analysis_db, 2, "2026-10-21T07:00:00", [steady(1800)], **{missing: False})

    body = get_aerobic(client_factory)

    assert ids(body) == [1]
    assert week(body, "2026-10-19")["runs"] == 1


def test_a_road_run_without_gps_still_counts_for_volume(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, "2026-10-27T07:00:00", [steady(1800)], gps=False)

    r = client_factory().get("/api/volume", params={"today": TODAY})

    assert r.json()["this_week"]["distance_m"] == pytest.approx(5400)


def fast_run(conn, activity_id: int, start_local: str, fast_s: int) -> None:
    """A steady 30 min run whose last `fast_s` samples read 8 m/s (GPS drift)."""
    add_hr_run(conn, activity_id, start_local, [steady(1800), steady(fast_s, speed=8.0)])


def test_more_than_sixty_seconds_above_seven_mps_is_gps_drift(analysis_db, client_factory):
    fast_run(analysis_db, 1, "2026-10-20T07:00:00", 60)
    fast_run(analysis_db, 2, "2026-10-21T07:00:00", 61)

    body = get_aerobic(client_factory)

    assert ids(body) == [1]
    assert body["method"]["params"]["max_speed_mps"] == 7.0
    assert body["method"]["params"]["max_fast_s"] == 60


def test_the_gps_drift_limits_come_from_config(data_dir, analysis_db, client_factory):
    (data_dir / "config.toml").write_text(
        "[aerobic]\nmax_fast_s = 61\nmax_speed_mps = 7.5\n", encoding="utf-8"
    )
    fast_run(analysis_db, 1, "2026-10-20T07:00:00", 61)
    fast_run(analysis_db, 2, "2026-10-21T07:00:00", 62)

    body = get_aerobic(client_factory)

    assert ids(body) == [1]
    assert body["method"]["params"]["max_speed_mps"] == 7.5
    assert body["method"]["params"]["max_fast_s"] == 61


def test_the_method_note_names_both_exclusion_rules(analysis_db, client_factory):
    description = get_aerobic(client_factory)["method"]["description"]

    assert "GPS" in description
    assert "海拔" in description
    assert "7 m/s" in description
    assert "60 秒" in description


def test_a_run_with_under_ten_minutes_of_steady_state_does_not_count(analysis_db, client_factory):
    # 19 min: 9 min of steady state after the 10 min warm-up.
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", [steady(1140)])
    add_hr_run(analysis_db, 2, "2026-10-21T07:00:00", [steady(1800)])
    add_hr_run(analysis_db, 3, "2026-10-22T07:00:00", [steady(1800)])

    body = get_aerobic(client_factory)

    assert week(body, "2026-10-19")["runs"] == 2
    assert ids(body) == [2, 3]


def test_the_value_is_read_off_the_hr_line_at_the_reference_hr(analysis_db, client_factory):
    # Two steady parts: 2.8 m/s at 140 bpm and 3.2 m/s at 150 bpm. The line
    # through them gives 3.0 m/s at 145 bpm, though no second was at 145.
    for i, day in enumerate(["2026-10-20", "2026-10-22"], start=1):
        add_hr_run(
            analysis_db,
            i,
            f"{day}T07:00:00",
            [steady(1500, speed=2.8, hr=140), steady(900, speed=3.2, hr=150)],
        )

    body = get_aerobic(client_factory)

    assert body["runs"][0]["speed_mps"] == pytest.approx(3.0, abs=0.005)
    assert week(body, "2026-10-19")["speed_mps"] == pytest.approx(3.0, abs=0.005)


def test_uphill_running_is_converted_to_flat_speed_with_minetti(analysis_db, client_factory):
    # 3.0 m/s up a steady 5 % grade costs as much as 3.904 m/s on the flat.
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", [steady(1800, grade=0.05)])

    [r] = get_aerobic(client_factory)["runs"]

    assert r["speed_mps"] == pytest.approx(3.9043, abs=0.001)


def test_grade_is_clipped_at_fifteen_percent(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", [steady(1800, speed=2.0, grade=0.25)])

    [r] = get_aerobic(client_factory)["runs"]

    # 2.0 x Cr(0.15) / Cr(0) = 2.0 x 7.4170 / 3.6
    assert r["speed_mps"] == pytest.approx(4.1206, abs=0.001)


def test_seconds_outside_the_hr_band_are_not_steady(analysis_db, client_factory):
    # 165 bpm is 20 above the reference: never steady. 158 is inside +-15.
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", [steady(1800, hr=165)])
    add_hr_run(analysis_db, 2, "2026-10-21T07:00:00", [steady(1800, hr=158)])

    assert ids(get_aerobic(client_factory)) == [2]


def test_hr_locked_on_cadence_is_not_steady(analysis_db, client_factory):
    # 150 spm and 150 bpm: the optical sensor is reading the arm swing.
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", [steady(1800, hr=150, cadence=75)])
    add_hr_run(analysis_db, 2, "2026-10-21T07:00:00", [steady(1800, hr=150, cadence=85)])

    assert ids(get_aerobic(client_factory)) == [2]


def test_changing_speed_is_not_steady(analysis_db, client_factory):
    # Speed alternates 2.6 / 3.4 m/s every minute: the 30 s mean moves far
    # more than 5 % within any 60 s window.
    surges = [steady(60, speed=2.6 if k % 2 else 3.4) for k in range(30)]
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", surges)

    assert get_aerobic(client_factory)["runs"] == []


def test_walking_seconds_are_not_steady(analysis_db, client_factory):
    # Brisk walking at 145 bpm: 110 spm is below the 140 spm running threshold.
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", [steady(1800, speed=1.6, cadence=55)])

    assert get_aerobic(client_factory)["runs"] == []


def add_week(conn, first_id: int, monday: str, speed: float) -> int:
    """Two valid runs (Tue, Wed) at `speed`; returns the next free id."""
    for k, d in enumerate((1, 2)):
        add_hr_run(
            conn, first_id + k, f"{day_after(monday, d)}T07:00:00", [steady(1800, speed=speed)]
        )
    return first_id + 2


def test_rolling_median_covers_four_weeks_and_skips_empty_weeks(analysis_db, client_factory):
    # 10-12 has no runs.
    aid = 1
    for monday, speed in [
        ("2026-09-28", 2.8),
        ("2026-10-05", 3.0),
        ("2026-10-19", 3.2),
        ("2026-10-26", 3.4),
    ]:
        aid = add_week(analysis_db, aid, monday, speed)

    body = get_aerobic(client_factory)

    assert week(body, "2026-10-12")["speed_mps"] is None
    assert week(body, "2026-10-12")["rolling_speed_mps"] is None
    # 10-19: 09-28 (2.8), 10-05 (3.0), 10-12 (empty), 10-19 (3.2) -> 3.0
    assert week(body, "2026-10-19")["rolling_speed_mps"] == pytest.approx(3.0, abs=1e-6)
    # 10-26: 10-05, 10-12 (empty), 10-19, 10-26 -> median(3.0, 3.2, 3.4) = 3.2
    assert week(body, "2026-10-26")["rolling_speed_mps"] == pytest.approx(3.2, abs=1e-6)
    assert week(body, "2026-10-26")["rolling_pace_s_per_km"] == pytest.approx(312.5, abs=0.01)
    assert week(body, "2026-10-26")["complete"] is False


def test_rolling_median_reaches_back_before_the_range(analysis_db, client_factory):
    # The 6-month range starts 2026-05-04; the three weeks before it count
    # toward that week's rolling median.
    aid = 1
    for monday in ("2026-04-13", "2026-04-20", "2026-04-27"):
        aid = add_week(analysis_db, aid, monday, 2.0)
    add_week(analysis_db, aid, "2026-05-04", 3.0)

    body = get_aerobic(client_factory, "6m")
    first = body["weeks"][0]

    assert first["week_start"] == "2026-05-04"
    assert first["speed_mps"] == pytest.approx(3.0, abs=1e-6)
    assert first["rolling_speed_mps"] == pytest.approx(2.0, abs=1e-6)
    assert ids(body) == [7, 8]


@pytest.mark.parametrize(
    ("range_", "n_weeks", "first"),
    [("6m", 26, "2026-05-04"), ("1y", 52, "2025-11-03"), ("2y", 104, "2024-11-04")],
)
def test_range_sets_the_number_of_weeks(analysis_db, client_factory, range_, n_weeks, first):
    body = get_aerobic(client_factory, range_)

    assert body["range"] == range_
    assert len(body["weeks"]) == n_weeks
    assert body["weeks"][0]["week_start"] == first
    assert body["weeks"][-1]["week_start"] == "2026-10-26"


def test_all_starts_at_the_first_road_run(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, "2023-03-08T07:00:00", [steady(1800)])

    body = get_aerobic(client_factory, "all")

    assert body["weeks"][0]["week_start"] == "2023-03-06"
    assert body["weeks"][-1]["week_start"] == "2026-10-26"
    assert ids(body) == [1]


def test_an_unknown_range_is_rejected(analysis_db, client_factory):
    r = client_factory().get("/api/aerobic", params={"range": "3m", "today": TODAY})
    assert r.status_code == 422


def run_temperature(body: dict, activity_id: int) -> float | None:
    [r] = [r for r in body["runs"] if r["activity_id"] == activity_id]
    return r["temperature_c"]


# 2026-10-20T07:00 in Auckland (NZDT) is 2026-10-19T18:00Z; a 30 min run's
# midpoint is 18:15Z.
@pytest.mark.parametrize(
    ("hours", "expected"),
    [
        ({"2026-10-19T18:00:00Z": 10.0, "2026-10-19T19:00:00Z": 14.0}, 11.0),
        ({"2026-10-19T18:00:00Z": 10.0}, None),
        ({"2026-10-19T19:00:00Z": 14.0}, None),
        ({"2026-10-19T17:00:00Z": 10.0, "2026-10-19T19:00:00Z": 14.0}, None),
        ({"2026-10-19T18:00:00Z": None, "2026-10-19T19:00:00Z": 14.0}, None),
    ],
    ids=["between", "no-hour-after", "no-hour-before", "hours-two-apart", "null-hour"],
)
def test_run_air_temperature_is_interpolated_between_the_two_hours(
    analysis_db, client_factory, hours, expected
):
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", [steady(1800)])
    add_hourly_weather(analysis_db, hours)

    t = run_temperature(get_aerobic(client_factory), 1)

    assert t == (pytest.approx(expected) if expected is not None else None)


def test_a_midpoint_on_the_hour_takes_that_hour(analysis_db, client_factory):
    # 40 min from 18:40Z: the midpoint is 19:00Z exactly.
    add_hr_run(analysis_db, 1, "2026-10-20T07:40:00", [steady(2400)])
    add_hourly_weather(analysis_db, {"2026-10-19T19:00:00Z": 14.0})

    assert run_temperature(get_aerobic(client_factory), 1) == pytest.approx(14.0)


AT_18Z = {"2026-10-19T18:00:00Z": 10.0, "2026-10-19T19:00:00Z": 14.0}


@pytest.mark.parametrize(
    ("position", "expected"),
    [
        ((10.04, 20.04), 11.0),  # rounds onto the grid point
        ((10.2, 19.8), 11.0),  # 0.2° away in both
        ((10.3, 20.0), None),  # 0.3° north
        ((10.0, 19.7), None),  # 0.3° west
    ],
)
def test_only_runs_within_two_tenths_of_the_grid_point_get_air_temperature(
    analysis_db, client_factory, position, expected
):
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", [steady(1800)], position=position)
    add_hourly_weather(analysis_db, AT_18Z, grid=(10.0, 20.0))

    t = run_temperature(get_aerobic(client_factory), 1)

    assert t == (pytest.approx(expected) if expected is not None else None)


def test_with_several_grid_points_the_nearest_one_is_used(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", [steady(1800)], position=(10.1, 20.1))
    add_hourly_weather(analysis_db, AT_18Z, grid=(10.0, 20.0))
    add_hourly_weather(
        analysis_db,
        {"2026-10-19T18:00:00Z": 20.0, "2026-10-19T19:00:00Z": 24.0},
        grid=(10.2, 20.1),
    )

    assert run_temperature(get_aerobic(client_factory), 1) == pytest.approx(21.0)


def run_in_air(conn, activity_id: int, day: str, air_c: float, seconds: int = 1800) -> None:
    """A steady run at 07:00 on `day` with the air at `air_c` all around it."""
    start_utc = add_hr_run(conn, activity_id, f"{day}T07:00:00", [steady(seconds)])
    add_hourly_weather(conn, utc_hours(start_utc, [air_c, air_c]))


def two_weeks_at_21_9_and_22_0(conn) -> None:
    # Median, not mean: the 30 °C run would pull last-but-one week's mean above 22.
    for i, (day, air) in enumerate(
        [
            ("2026-10-13", 21.9),
            ("2026-10-14", 21.0),
            ("2026-10-15", 30.0),
            ("2026-10-20", 22.0),
            ("2026-10-21", 10.0),
            ("2026-10-22", 25.0),
        ]
    ):
        run_in_air(conn, i + 1, day, air)
    # Too short to be valid: its 40 °C does not count.
    run_in_air(conn, 9, "2026-10-16", 40.0, seconds=600)


def test_weekly_air_temperature_is_the_median_of_the_valid_runs(analysis_db, client_factory):
    two_weeks_at_21_9_and_22_0(analysis_db)

    body = get_aerobic(client_factory)

    assert week(body, "2026-10-12")["temperature_c"] == pytest.approx(21.9)
    assert week(body, "2026-10-19")["temperature_c"] == pytest.approx(22.0)
    assert week(body, "2026-10-05")["temperature_c"] is None


def test_a_week_at_22_degrees_or_more_is_hot(analysis_db, client_factory):
    two_weeks_at_21_9_and_22_0(analysis_db)

    body = get_aerobic(client_factory)

    assert week(body, "2026-10-12")["hot"] is False
    assert week(body, "2026-10-19")["hot"] is True
    assert week(body, "2026-10-05")["hot"] is False
    assert body["method"]["params"]["hot_week_c"] == 22.0


def test_the_hot_week_threshold_comes_from_config(data_dir, analysis_db, client_factory):
    (data_dir / "config.toml").write_text("[aerobic]\nhot_week_c = 21.5\n", encoding="utf-8")
    two_weeks_at_21_9_and_22_0(analysis_db)

    body = get_aerobic(client_factory)

    assert week(body, "2026-10-12")["hot"] is True
    assert week(body, "2026-10-19")["hot"] is True
    assert body["method"]["params"]["hot_week_c"] == 21.5


@pytest.mark.parametrize("table", ["empty", "missing"])
def test_without_hourly_weather_the_metric_still_works(analysis_db, client_factory, table):
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", [steady(1800, speed=3.0)])
    add_hr_run(analysis_db, 2, "2026-10-22T07:00:00", [steady(1800, speed=3.2)])
    if table == "missing":  # an analysis database from before importer migration 7
        analysis_db.execute("DROP TABLE hourly_weather")
        analysis_db.commit()

    body = get_aerobic(client_factory)
    w = week(body, "2026-10-19")

    assert w["speed_mps"] == pytest.approx(3.1, abs=1e-6)
    assert w["temperature_c"] is None
    assert w["hot"] is False
    assert [r["temperature_c"] for r in body["runs"]] == [None, None]


def test_the_method_note_explains_the_air_temperature(analysis_db, client_factory):
    body = get_aerobic(client_factory)
    text = body["method"]["description"]

    assert "Open-Meteo" in text
    assert "中点" in text
    assert "不做温度校正" in text
    assert "高温周" in text and "≥ 22 °C" in text


def test_a_run_without_gps_gets_no_air_temperature(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", [steady(1800)], gps=False)
    add_hourly_weather(analysis_db, AT_18Z)

    body = get_aerobic(client_factory)

    assert ids(body) == []
    assert week(body, "2026-10-19")["temperature_c"] is None


def test_runs_after_today_are_ignored(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, "2026-10-29T07:00:00", [steady(1800)])

    body = get_aerobic(client_factory)

    assert body["runs"] == []
    assert body["has_data"] is False


def test_thresholds_come_from_config_toml(data_dir, analysis_db, client_factory):
    (data_dir / "config.toml").write_text(
        "[aerobic]\nreference_hr = 160\nmin_steady_s = 300\n", encoding="utf-8"
    )
    # 20 min at 160 bpm: steady only with the band centred on 160, and long
    # enough only with the lowered minimum.
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", [steady(1200, hr=160)])

    body = get_aerobic(client_factory)

    assert ids(body) == [1]
    assert body["method"]["params"]["reference_hr"] == 160
    assert body["method"]["params"]["min_steady_s"] == 300


def test_without_a_database_every_week_is_empty(data_dir, client_factory):
    body = get_aerobic(client_factory)

    assert body["has_data"] is False
    assert len(body["weeks"]) == 26
    assert all(w["speed_mps"] is None for w in body["weeks"])
    assert body["runs"] == []
    assert body["method"]["params"]["reference_hr"] == 145
    assert "Minetti" in body["method"]["description"]
