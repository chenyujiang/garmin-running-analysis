"""Seam: GET /api/parkruns, the Auckland parkrun courses with their elevation
profile, climbs, even-effort splits and pacing advice. The profiles are the
packaged `parkrun_courses.json`; the pacing rules are checked on synthetic
profiles."""

import json

import pytest

from running.aerobic import CR_FLAT, minetti_cr
from running.parkruns import (
    COURSES,
    DATA_FILE,
    climbs,
    effort_cost,
    parkrun_courses,
    splits,
    tag,
)

STEP = 25.0
N = 201  # 5 km every 25 m


def test_lists_every_course_easiest_first_without_user_data(data_dir, client_factory):
    r = client_factory().get("/api/parkruns")
    assert r.status_code == 200
    body = r.json()
    assert body["target_s"] == 1200
    slugs = [c["slug"] for c in body["courses"]]
    assert sorted(slugs) == sorted(COURSES)
    gains = [c["gain_m"] for c in body["courses"]]
    assert gains == sorted(gains)
    for c in body["courses"]:
        assert len(c["elevation_m"]) == N
        assert c["step_m"] == STEP
        assert [s["km"] for s in c["splits"]] == [1, 2, 3, 4, 5]
        assert sum(s["time_s"] for s in c["splits"]) == pytest.approx(c["estimate_s"], abs=0.5)
        assert c["delta_s"] == pytest.approx(c["estimate_s"] - 1200, abs=0.1)
        assert c["delta_s"] >= 0  # even effort: hills never make 5 km faster
        assert c["tag"] in {"平路", "微起伏", "起伏", "多坡"}
        assert c["strategy"]
        assert c["url"] == f"https://www.parkrun.co.nz/{c['slug']}/course/"


def test_target_time_scales_every_estimate(data_dir, client_factory):
    client = client_factory()
    base = {c["slug"]: c for c in client.get("/api/parkruns").json()["courses"]}
    slow = client.get("/api/parkruns", params={"target_s": 1500}).json()
    assert slow["target_s"] == 1500
    for c in slow["courses"]:
        assert c["estimate_s"] == pytest.approx(base[c["slug"]]["estimate_s"] * 1.25, abs=0.5)


@pytest.mark.parametrize("target_s", [599, 3601])
def test_rejects_target_out_of_range(data_dir, client_factory, target_s):
    r = client_factory().get("/api/parkruns", params={"target_s": target_s})
    assert r.status_code == 422


def test_profile_file_holds_elevations_only():
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    assert set(data) == {"source", "step_m", "courses"}
    for c in data["courses"].values():
        assert set(c) == {"elevation_m", "fit_note"}
        assert all(isinstance(v, int | float) for v in c["elevation_m"])


def test_flat_course_runs_at_target_pace():
    sp = splits([10.0] * N, STEP, 1200)
    assert [s["pace_s_per_km"] for s in sp] == [240.0] * 5
    assert [s["net_m"] for s in sp] == [0.0] * 5


def test_uphill_costs_minetti_downhill_gives_back_half():
    assert effort_cost(0.05) == pytest.approx(minetti_cr(0.05))
    saving = CR_FLAT - minetti_cr(-0.05)
    assert effort_cost(-0.05) == pytest.approx(CR_FLAT - saving / 2)
    assert effort_cost(0.30) == effort_cost(0.15)  # clamped

    up_then_down = [min(i, 200 - i) * 0.1 for i in range(N)]  # 10 m up, 10 m down
    sp = splits(up_then_down, STEP, 1200)
    assert sp[0]["pace_s_per_km"] > 240 > sp[-1]["pace_s_per_km"]
    assert sum(s["time_s"] for s in sp) > 1200  # an out-and-back over a hill is slower


def test_climbs_trim_level_ground_and_skip_small_bumps():
    # flat 1 km, 20 m up over 500 m, flat with a 0.8 m dip, 20 m down at the end
    ele = [0.0] * 40 + [i * 1.0 for i in range(1, 21)] + [20.0] * 60
    ele += [20.0 - min(i, 8 - i) * 0.2 for i in range(9)] + [20.0] * 52
    ele += [20.0 - i * 1.0 for i in range(1, 21)]
    assert len(ele) == N
    found = climbs(ele, STEP)
    assert [(c["kind"], c["start_m"], c["end_m"], c["change_m"]) for c in found] == [
        ("up", 975.0, 1475.0, 20.0),
        ("down", 4500.0, 5000.0, -20.0),
    ]
    assert found[0]["grade"] == pytest.approx(20 / 500, abs=1e-4)


def test_tag_from_gain_and_steepest_grade():
    assert tag(10, 0.02) == "平路"
    assert tag(25, 0.03) == "微起伏"
    assert tag(25, 0.09) == "起伏"
    assert tag(80, 0.12) == "多坡"


def test_strategy_warns_about_a_climb_to_the_finish():
    c = next(c for c in parkrun_courses()["courses"] if c["slug"] == "northernpathway")
    assert c["tag"] == "多坡"
    assert any("最后 1 km 上升" in s for s in c["strategy"])
    assert c["fit_note"]
