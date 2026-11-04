"""Seam 3: the analysis report on the detail page, GET /api/activities/{id} `report`.

Six fixed rules (spec "分析报告"), each item `rule, verdict, text, params`.
Config (conftest): LTHR 170 from 2021-08-01, so the zone floors are 144.5,
153, 161.5 and 170 bpm; reference HR 145. Synthetic runs are flat, 1 Hz,
cadence 170 spm (all seconds are running).
"""

from datetime import date, timedelta

import pytest
from synthetic import insert_activity
from synthetic_aerobic import add_hourly_weather, add_hr_run, steady, utc_hours

START_LOCAL = "2026-10-20T07:00:00"  # a Tuesday


def get_report(client_factory, activity_id: int) -> list[dict]:
    r = client_factory().get(f"/api/activities/{activity_id}")
    assert r.status_code == 200, r.text
    report = r.json()["report"]
    assert report["method"]["name"]
    return report["items"]


def item(items: list[dict], rule: str) -> dict:
    [found] = [i for i in items if i["rule"] == rule]
    assert found["text"]
    return found


def test_an_easy_run_is_classified_easy(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(1800, hr=140.0)])

    t = item(get_report(client_factory, 1), "training_type")

    assert t["verdict"] == "neutral"
    assert t["params"]["type"] == "easy"
    assert t["params"]["z1_z2_share"] == pytest.approx(1.0)
    assert t["params"]["easy_share"] == 0.8


def set_config(data_dir, section: str, **values) -> None:
    with (data_dir / "config.toml").open("a", encoding="utf-8") as f:
        f.write(f"\n[{section}]\n")
        for k, v in values.items():
            f.write(f"{k} = {v}\n")


# --- training type -------------------------------------------------------------


def intervals(reps: int) -> list:
    """Warm-up, `reps` x (2 min fast, 2 min slow), cool-down. Speeds 3.0 m/s
    (900 s), 4.0 (fast) and 2.5 (recovery): the median running speed is 3.0,
    so the fast stretches are 33 % above it and the recoveries below it."""
    out = [steady(600, speed=3.0, hr=140.0)]
    for _ in range(reps):
        out += [steady(120, speed=4.0, hr=165.0), steady(120, speed=2.5, hr=150.0)]
    return [*out, steady(300, speed=3.0, hr=140.0)]


def test_three_fast_reps_with_recoveries_are_intervals(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, START_LOCAL, intervals(3))

    t = item(get_report(client_factory, 1), "training_type")

    assert t["params"]["type"] == "interval"
    assert t["params"]["interval_reps"] == 3
    assert t["params"]["median_speed_mps"] == pytest.approx(3.0)


def test_two_fast_reps_are_not_intervals(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, START_LOCAL, intervals(2))

    t = item(get_report(client_factory, 1), "training_type")

    assert t["params"]["type"] != "interval"
    assert t["params"]["interval_reps"] == 2


def test_the_rep_count_comes_from_the_report_config(data_dir, analysis_db, client_factory):
    set_config(data_dir, "report", interval_min_reps=4)
    add_hr_run(analysis_db, 1, START_LOCAL, intervals(3))

    t = item(get_report(client_factory, 1), "training_type")

    assert t["params"]["type"] != "interval"
    assert t["params"]["interval_min_reps"] == 4


def test_a_long_stretch_in_z3_z4_is_a_tempo_run(analysis_db, client_factory):
    # 1200 s of 2100 at 158 bpm (Z3): 57 %, one unbroken 20-minute stretch.
    add_hr_run(
        analysis_db,
        1,
        START_LOCAL,
        [steady(600, hr=140.0), steady(1200, hr=158.0), steady(300, hr=140.0)],
    )

    t = item(get_report(client_factory, 1), "training_type")

    assert t["params"]["type"] == "tempo"
    assert t["params"]["z3_z4_share"] == pytest.approx(1200 / 2100, abs=0.002)
    assert t["params"]["longest_z3_z4_s"] == pytest.approx(1200, abs=30)


TEMPO_IN_PIECES = [
    steady(300, hr=140.0),
    steady(500, hr=158.0),
    steady(120, hr=140.0),
    steady(500, hr=158.0),
]


def test_z3_z4_in_short_pieces_is_not_a_tempo_run(analysis_db, client_factory):
    # 70 % in Z3, but no stretch reaches 15 minutes; Z1-Z2 30 %, so mixed.
    add_hr_run(analysis_db, 1, START_LOCAL, TEMPO_IN_PIECES)

    t = item(get_report(client_factory, 1), "training_type")

    assert t["params"]["type"] == "mixed"
    assert t["params"]["z3_z4_share"] == pytest.approx(1000 / 1420, abs=0.002)
    assert t["params"]["longest_z3_z4_s"] < 900


def test_tempo_thresholds_come_from_the_report_config(data_dir, analysis_db, client_factory):
    set_config(data_dir, "report", tempo_min_s=480)
    add_hr_run(analysis_db, 1, START_LOCAL, TEMPO_IN_PIECES)

    t = item(get_report(client_factory, 1), "training_type")

    assert t["params"]["type"] == "tempo"


def test_an_easy_hour_is_a_long_run(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(3700, hr=140.0)])

    t = item(get_report(client_factory, 1), "training_type")

    assert t["params"]["type"] == "long"
    assert t["params"]["long_easy_share"] == 0.7


def test_half_easy_half_z5_is_mixed(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(900, hr=140.0), steady(900, hr=175.0)])

    t = item(get_report(client_factory, 1), "training_type")

    assert t["params"]["type"] == "mixed"
    assert t["params"]["z1_z2_share"] == pytest.approx(0.5, abs=0.002)


def test_without_heart_rate_only_intervals_can_be_told(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(1800, hr=None)])

    t = item(get_report(client_factory, 1), "training_type")

    assert t["verdict"] == "unknown"
    assert "也不是间歇跑" in t["text"]


# --- aerobic value against the recent median ----------------------------------


def add_baseline(conn) -> None:
    """Two valid runs at 3.0 m/s and the reference HR in the week before:
    aerobic value 3.0 m/s each, so the 4-week median is 3.0."""
    add_hr_run(conn, 101, "2026-10-13T07:00:00", [steady(1800, speed=3.0, hr=145.0)])
    add_hr_run(conn, 102, "2026-10-15T07:00:00", [steady(1800, speed=3.0, hr=145.0)])


@pytest.mark.parametrize(("speed", "verdict"), [(3.1, "good"), (3.03, "neutral"), (2.9, "watch")])
def test_the_aerobic_value_against_the_4_week_median(analysis_db, client_factory, speed, verdict):
    add_baseline(analysis_db)
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(1800, speed=speed, hr=145.0)])

    a = item(get_report(client_factory, 1), "aerobic")

    assert a["verdict"] == verdict
    assert a["params"]["baseline_speed_mps"] == pytest.approx(3.0)
    assert a["params"]["baseline_weeks"] == 1
    assert a["params"]["change"] == pytest.approx(speed / 3.0 - 1, abs=1e-6)
    assert a["params"]["aerobic_change"] == 0.02


def test_the_aerobic_threshold_comes_from_the_report_config(data_dir, analysis_db, client_factory):
    set_config(data_dir, "report", aerobic_change=0.05)
    add_baseline(analysis_db)
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(1800, speed=3.1, hr=145.0)])

    a = item(get_report(client_factory, 1), "aerobic")

    assert a["verdict"] == "neutral"


def test_without_recent_aerobic_values_there_is_nothing_to_compare(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(1800, speed=3.0, hr=145.0)])

    a = item(get_report(client_factory, 1), "aerobic")

    assert a["verdict"] == "unknown"
    assert a["params"]["baseline_speed_mps"] is None
    assert "4 周" in a["text"]


def test_a_run_that_does_not_count_says_why(analysis_db, client_factory):
    add_baseline(analysis_db)
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(1800)], "treadmill_running")

    a = item(get_report(client_factory, 1), "aerobic")

    assert a["verdict"] == "unknown"
    assert a["text"].startswith("本次不计入有氧能力：")


# --- HR drift --------------------------------------------------------------------


def test_61_minutes_with_drift_over_5_percent_is_watch(analysis_db, client_factory):
    # Same pace, HR 140 then 155 bpm: EF falls in the second half.
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(1830, hr=140.0), steady(1830, hr=155.0)])

    r = client_factory().get("/api/activities/1").json()
    d = item(r["report"]["items"], "drift")

    assert d["verdict"] == "watch"
    assert d["params"]["decoupling_pct"] == pytest.approx(r["metrics"]["ef"]["decoupling_pct"])
    assert d["params"]["decoupling_pct"] > 5
    assert d["params"]["decoupling_limit_pct"] == 5


def test_61_steady_minutes_have_no_drift(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(3660, hr=150.0)])

    d = item(get_report(client_factory, 1), "drift")

    assert d["verdict"] == "good"
    assert d["params"]["decoupling_pct"] == pytest.approx(0.0, abs=1e-6)


def test_under_60_minutes_only_ef_is_given(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(1800, hr=150.0)])

    d = item(get_report(client_factory, 1), "drift")

    assert d["verdict"] == "neutral"
    assert d["params"]["decoupling_pct"] is None
    assert "不判漂移" in d["text"]


# --- pacing ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("second", "split", "verdict", "change"),
    [
        (3.09, "negative", "good", 0.03),
        (3.03, "even", "good", 0.01),
        (2.91, "positive", "watch", -0.03),
    ],
)
def test_pacing_compares_the_gap_pace_of_the_two_halves(
    analysis_db, client_factory, second, split, verdict, change
):
    # Equal distances: 3600 m at 3.0 m/s, then 3600 m at the second speed.
    add_hr_run(
        analysis_db,
        1,
        START_LOCAL,
        [steady(1200, speed=3.0), steady(round(3600 / second), speed=second)],
    )

    p = item(get_report(client_factory, 1), "pacing")

    assert p["params"]["split"] == split
    assert p["verdict"] == verdict
    assert p["params"]["change"] == pytest.approx(change, abs=0.003)
    assert p["params"]["split_change"] == 0.02


def test_the_split_threshold_comes_from_the_report_config(data_dir, analysis_db, client_factory):
    set_config(data_dir, "report", split_change=0.04)
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(1200, speed=3.0), steady(1165, speed=3.09)])

    p = item(get_report(client_factory, 1), "pacing")

    assert p["params"]["split"] == "even"


def test_intervals_are_not_judged_on_pacing(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, START_LOCAL, intervals(3))

    p = item(get_report(client_factory, 1), "pacing")

    assert p["verdict"] == "unknown"
    assert "间歇" in p["text"]


# --- load ------------------------------------------------------------------------

HOUR_AT_MAX = 261.9248  # 60 x 0.64 x e^1.92 TRIMP (test_load_api)


def test_a_first_hard_hour_is_a_load_spike(analysis_db, client_factory):
    # No records: TRIMP from the summary HR. Nothing before it, so TSB is 0
    # before the run; the next day CTL = L/42 and ATL = L/7.
    insert_activity(analysis_db, 1, START_LOCAL, distance_m=10000, duration_s=3600, avg_hr_bpm=192)

    lo = item(get_report(client_factory, 1), "load")

    assert lo["verdict"] == "watch"
    p = lo["params"]
    assert p["trimp"] == pytest.approx(HOUR_AT_MAX, abs=0.01)
    assert p["week_share"] == pytest.approx(1.0)
    assert p["week_start"] == "2026-10-19"
    assert p["tsb_before"] == pytest.approx(0.0)
    assert p["tsb_after"] == pytest.approx(HOUR_AT_MAX / 42 - HOUR_AT_MAX / 7, abs=0.01)
    assert p["atl_ctl_ratio"] == pytest.approx(6.0)
    assert "负荷突增" in lo["text"]


def test_the_same_load_every_day_is_no_spike(analysis_db, client_factory):
    # The same hour on each of the 60 days before: ATL/CTL is about 1.3.
    first = date(2026, 8, 21)
    for k in range(60):
        day = (first + timedelta(days=k)).isoformat()
        insert_activity(
            analysis_db,
            100 + k,
            f"{day}T07:00:00",
            distance_m=10000,
            duration_s=3600,
            avg_hr_bpm=192,
        )
    insert_activity(analysis_db, 1, START_LOCAL, distance_m=10000, duration_s=3600, avg_hr_bpm=192)

    lo = item(get_report(client_factory, 1), "load")

    assert lo["verdict"] == "neutral"
    assert lo["params"]["week_share"] == pytest.approx(0.5)  # Monday's hour and this one
    assert 1.2 < lo["params"]["atl_ctl_ratio"] < 1.5


# --- heat ------------------------------------------------------------------------


@pytest.mark.parametrize(("temp", "verdict"), [(25.0, "watch"), (15.0, "neutral")])
def test_hot_air_is_a_warning(analysis_db, client_factory, temp, verdict):
    start_utc = add_hr_run(analysis_db, 1, START_LOCAL, [steady(1800)])
    add_hourly_weather(analysis_db, utc_hours(start_utc, [temp, temp]))

    h = item(get_report(client_factory, 1), "heat")

    assert h["verdict"] == verdict
    assert h["params"] == {"air_temperature_c": pytest.approx(temp), "hot_c": 22.0}


def test_the_heat_threshold_is_the_hot_week_setting(data_dir, analysis_db, client_factory):
    cfg = data_dir / "config.toml"
    toml = cfg.read_text(encoding="utf-8")
    cfg.write_text(
        toml.replace("reference_hr = 145", "reference_hr = 145\nhot_week_c = 14"), "utf-8"
    )
    start_utc = add_hr_run(analysis_db, 1, START_LOCAL, [steady(1800)])
    add_hourly_weather(analysis_db, utc_hours(start_utc, [15.0, 15.0]))

    h = item(get_report(client_factory, 1), "heat")

    assert h["verdict"] == "watch"


def test_without_air_temperature_there_is_no_heat_item(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(1800)])

    items = get_report(client_factory, 1)

    assert [i["rule"] for i in items] == ["training_type", "aerobic", "drift", "pacing", "load"]


# --- what cannot be judged -------------------------------------------------------


def test_a_ride_gets_load_but_no_running_rules(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(1800, speed=7.0)], "cycling")

    items = get_report(client_factory, 1)

    for rule in ("training_type", "aerobic", "drift", "pacing"):
        i = item(items, rule)
        assert i["verdict"] == "unknown", rule
        assert "仅跑步类活动" in i["text"], rule
    assert item(items, "load")["verdict"] != "unknown"
