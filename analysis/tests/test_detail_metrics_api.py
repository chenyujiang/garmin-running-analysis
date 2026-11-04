"""Seam 3: this run's metrics on the detail page, GET /api/activities/{id} `metrics`.

TRIMP (the load section's per-second Banister sum), time in each HR zone
(Friel's running LTHR zones), the aerobic value (GAP pace at the reference HR,
or why the run does not count), EF and, from 60 minutes, decoupling (the
long-run table's definitions).

Config (conftest): LTHR 170 from 2021-08-01, so the zone floors are
85 % = 144.5, 90 % = 153, 95 % = 161.5 and 100 % = 170 bpm. Records are 1 Hz;
each sample owns the second ending at it, so a stretch of N seconds is N
seconds in its zone.
"""

import pytest
from synthetic import insert_activity
from synthetic_aerobic import add_hr_run, steady

START_LOCAL = "2026-10-20T07:00:00"


def get_metrics(client_factory, activity_id: int) -> dict:
    r = client_factory().get(f"/api/activities/{activity_id}")
    assert r.status_code == 200, r.text
    return r.json()["metrics"]


def zone_seconds(m: dict) -> list[float]:
    return [z["seconds"] for z in m["zones"]["zones"]]


def test_time_in_each_hr_zone(analysis_db, client_factory):
    add_hr_run(
        analysis_db,
        1,
        START_LOCAL,
        [
            steady(600, hr=140.0),  # Z1 < 144.5
            steady(300, hr=150.0),  # Z2 144.5..153
            steady(300, hr=155.0),  # Z3 153..161.5
            steady(200, hr=165.0),  # Z4 161.5..170
            steady(100, hr=172.0),  # Z5 >= 170
        ],
    )

    m = get_metrics(client_factory, 1)

    assert zone_seconds(m) == pytest.approx([600, 300, 300, 200, 100])
    z = m["zones"]
    assert z["lthr_bpm"] == 170
    assert z["lthr_pct"] == [85, 90, 95, 100]
    assert [x["zone"] for x in z["zones"]] == [1, 2, 3, 4, 5]
    assert [x["low_bpm"] for x in z["zones"]] == pytest.approx([None, 144.5, 153.0, 161.5, 170.0])
    assert z["total_s"] == pytest.approx(1500)
    assert z["zones"][0]["share"] == pytest.approx(0.4)
    assert m["method"]["name"]
    assert m["method"]["params"]["lthr_pct"] == [85, 90, 95, 100]


def add_physiology(data_dir, effective_from: str, lthr: int, hr_max: int = 192) -> None:
    with (data_dir / "config.toml").open("a", encoding="utf-8") as f:
        f.write(
            f"\n[[physiology]]\neffective_from = {effective_from}\n"
            f"hr_max = {hr_max}\nhr_rest = 55\nlthr = {lthr}\n"
        )


def test_the_lthr_is_the_one_in_effect_on_the_activity_date(data_dir, analysis_db, client_factory):
    # 150 bpm is Z2 of LTHR 170 (144.5..153) and Z3 of LTHR 160 (144..152),
    # the set in effect from 2026-10-21.
    add_physiology(data_dir, "2026-10-21", lthr=160)
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", [steady(600, hr=150.0)])
    add_hr_run(analysis_db, 2, "2026-10-21T07:00:00", [steady(600, hr=150.0)])

    before = get_metrics(client_factory, 1)
    after = get_metrics(client_factory, 2)

    assert before["zones"]["lthr_bpm"] == 170
    assert zone_seconds(before) == pytest.approx([0, 600, 0, 0, 0])
    assert after["zones"]["lthr_bpm"] == 160
    assert after["zones"]["physiology_effective_from"] == "2026-10-21"
    assert zone_seconds(after) == pytest.approx([0, 0, 600, 0, 0])


def test_zone_floors_come_from_the_zones_config(data_dir, analysis_db, client_factory):
    with (data_dir / "config.toml").open("a", encoding="utf-8") as f:
        f.write("\n[zones]\nlthr_pct = [80, 90, 95, 100]\n")
    # 140 bpm is 82 % of 170: Z1 by default, Z2 with the first floor at 80 %.
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(600, hr=140.0)])

    m = get_metrics(client_factory, 1)

    assert zone_seconds(m) == pytest.approx([0, 600, 0, 0, 0])
    assert m["zones"]["zones"][1]["low_bpm"] == pytest.approx(136.0)
    assert m["method"]["params"]["lthr_pct"] == [80, 90, 95, 100]


def drop_records(conn, activity_id: int, first_s: int, last_s: int) -> None:
    """Delete the samples at t = first_s..last_s: the watch was paused."""
    rows = conn.execute(
        "SELECT timestamp FROM records WHERE activity_id = ? ORDER BY timestamp", (activity_id,)
    ).fetchall()
    conn.executemany(
        "DELETE FROM records WHERE activity_id = ? AND timestamp = ?",
        [(activity_id, r[0]) for r in rows[first_s : last_s + 1]],
    )
    conn.commit()


def test_zones_count_only_seconds_with_hr_outside_pauses(analysis_db, client_factory):
    # 600 s at 150 bpm, 300 s without HR, 600 s at 165 bpm; t = 1201..1260 are
    # removed (a pause: the sample at 1261 follows a 61 s gap and owns nothing).
    add_hr_run(
        analysis_db,
        1,
        START_LOCAL,
        [steady(600, hr=150.0), steady(300, hr=None), steady(600, hr=165.0)],
    )
    drop_records(analysis_db, 1, 1201, 1260)

    m = get_metrics(client_factory, 1)

    assert zone_seconds(m) == pytest.approx([0, 600, 0, 539, 0])
    assert m["zones"]["total_s"] == pytest.approx(1139)


def load_trimp(client_factory, day: str) -> float:
    r = client_factory().get("/api/load", params={"today": day})
    assert r.status_code == 200, r.text
    return next(p["trimp"] for p in r.json()["series"] if p["date"] == day)


def test_trimp_matches_the_load_section_for_the_same_activity(analysis_db, client_factory):
    # Uneven effort with a pause: 1200 s at 150, 30 s removed, 1200 s at 175.
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(1200, hr=150.0), steady(1200, hr=175.0)])
    drop_records(analysis_db, 1, 1500, 1529)

    m = get_metrics(client_factory, 1)

    assert m["trimp"] > 0
    assert m["trimp"] == pytest.approx(load_trimp(client_factory, START_LOCAL[:10]), rel=1e-9)
    assert m["trimp_source"] == "records"


def test_one_hour_at_hr_max_is_the_known_trimp(analysis_db, client_factory):
    # 60 x 0.64 x e^1.92 (test_load_api): x = 1 at HRmax 192.
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(3599, hr=192.0)])

    m = get_metrics(client_factory, 1)

    # 3599 records-to-next gaps of 1 s plus the last sample's 1 s.
    assert m["trimp"] == pytest.approx(261.9248, abs=0.01)


def test_trimp_from_the_summary_hr_when_there_are_no_records(analysis_db, client_factory):
    insert_activity(analysis_db, 1, START_LOCAL, distance_m=10000, duration_s=3600, avg_hr_bpm=192)

    m = get_metrics(client_factory, 1)

    assert m["trimp"] == pytest.approx(261.9248, abs=0.01)
    assert m["trimp_source"] == "summary_hr"
    assert m["zones"] is None


def test_without_heart_rate_there_are_no_zones_and_the_reason(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(600, hr=None)])

    m = get_metrics(client_factory, 1)

    assert m["zones"] is None
    assert m["unavailable"]["zones"] == "没有心率"
    assert m["trimp"] is None
    assert m["unavailable"]["trimp"] == "没有心率"


def test_the_aerobic_value_is_the_one_in_the_aerobic_trend(analysis_db, client_factory):
    # 2.8 m/s at 140 bpm then 3.2 m/s at 150 bpm: the HR line gives 3.0 m/s
    # at the reference 145 bpm (test_aerobic_api).
    add_hr_run(
        analysis_db,
        1,
        START_LOCAL,
        [steady(1500, speed=2.8, hr=140.0), steady(900, speed=3.2, hr=150.0)],
    )

    m = get_metrics(client_factory, 1)
    trend = client_factory().get("/api/aerobic", params={"range": "6m", "today": "2026-10-28"})
    [run] = trend.json()["runs"]

    a = m["aerobic"]
    assert a["speed_mps"] == pytest.approx(3.0, abs=0.005)
    assert a["speed_mps"] == pytest.approx(run["speed_mps"], rel=1e-12)
    assert a["pace_s_per_km"] == pytest.approx(1000 / run["speed_mps"])
    assert a["steady_s"] == pytest.approx(run["steady_s"])
    assert a["reference_hr"] == 145
    assert "aerobic" not in m["unavailable"]


@pytest.mark.parametrize(
    ("kind", "stretches", "kw", "reason"),
    [
        ("treadmill_running", [steady(1800)], {}, "不是户外路跑"),
        ("trail_running", [steady(1800)], {}, "不是户外路跑"),
        ("running", [steady(1800)], {"gps": False}, "没有 GPS 位置"),
        ("running", [steady(1800)], {"altitude": False}, "没有海拔"),
        ("running", [steady(1800), steady(61, speed=8.0)], {}, "GPS 漂移"),
        ("running", [steady(1800, hr=None)], {}, "没有心率"),
        ("running", [steady(1100)], {}, "不足 10 分钟"),
        ("cycling", [steady(1800, speed=7.0)], {}, "仅跑步类活动"),
    ],
)
def test_a_run_that_does_not_count_for_the_aerobic_value_says_why(
    analysis_db, client_factory, kind, stretches, kw, reason
):
    add_hr_run(analysis_db, 1, START_LOCAL, stretches, kind, **kw)

    m = get_metrics(client_factory, 1)

    assert m["aerobic"] is None
    assert reason in m["unavailable"]["aerobic"]


def long_run(client_factory, activity_id: int) -> dict:
    r = client_factory().get("/api/long-runs", params={"today": "2026-10-28"})
    assert r.status_code == 200, r.text
    return next(x for x in r.json()["runs"] if x["activity_id"] == activity_id)


def test_ef_and_decoupling_of_a_60_minute_run(analysis_db, client_factory):
    # 3.0 m/s on the flat at 150 bpm: EF = 180 m/min / 150 bpm = 1.2, both
    # halves alike, so no decoupling.
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(3600, speed=3.0, hr=150.0)])

    m = get_metrics(client_factory, 1)

    assert m["ef"]["ef"] == pytest.approx(1.2, abs=1e-6)
    assert m["ef"]["decoupling_pct"] == pytest.approx(0.0, abs=1e-6)
    assert m["ef"]["decoupling_high"] is False
    assert "ef" not in m["unavailable"]
    assert "decoupling" not in m["unavailable"]


def test_ef_and_decoupling_are_the_long_run_table_values(analysis_db, client_factory):
    # HR drifts from 140 to 155 bpm (both inside the steady HR band) at the same
    # pace: EF falls in the second half.
    add_hr_run(
        analysis_db,
        1,
        START_LOCAL,
        [steady(1800, speed=3.0, hr=140.0), steady(1800, speed=3.0, hr=155.0)],
    )

    m = get_metrics(client_factory, 1)
    row = long_run(client_factory, 1)

    for key in ("ef", "ef_first", "ef_second", "decoupling_pct", "steady_s"):
        assert m["ef"][key] == pytest.approx(row[key], rel=1e-12), key
    assert m["ef"]["decoupling_pct"] > 5
    assert m["ef"]["decoupling_high"] is True


def test_a_59_minute_run_has_ef_but_no_decoupling(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(3540, speed=3.0, hr=150.0)])

    m = get_metrics(client_factory, 1)

    assert m["ef"]["ef"] == pytest.approx(1.2, abs=1e-6)
    assert m["ef"]["decoupling_pct"] is None
    assert m["ef"]["decoupling_high"] is False
    assert "不足 60 分钟" in m["unavailable"]["decoupling"]


@pytest.mark.parametrize(
    ("kind", "reason"),
    [("cycling", "仅跑步类活动"), ("treadmill_running", "不是户外路跑")],
)
def test_no_ef_for_a_run_off_the_road_or_another_sport(analysis_db, client_factory, kind, reason):
    add_hr_run(analysis_db, 1, START_LOCAL, [steady(3600)], kind)

    m = get_metrics(client_factory, 1)

    assert m["ef"] is None
    assert reason in m["unavailable"]["ef"]
