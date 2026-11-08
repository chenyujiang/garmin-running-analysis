"""Seam: the 5K plan after Daniels (GET /api/plan5k).

Pace expectations are the published VDOT 50 table values (Daniels' Running
Formula): M 4:31/km, T 4:15/km, I 3:55/km, R 88 s per 400 m.
"""

import json
from datetime import date, timedelta

import pytest
from synthetic import insert_activity

from running.plan5k import CAP, training_paces

TODAY = "2026-10-28"
HEADER = "date,activity_id,distance_m,time_s,all_out,note\n"


def plan(client_factory, **params) -> dict:
    r = client_factory().get("/api/plan5k", params={"today": TODAY, **params})
    assert r.status_code == 200, r.text
    return r.json()


def weekly_km(conn, km: float, weeks: int = 8) -> None:
    for i in range(weeks):
        day = date.fromisoformat(TODAY) - timedelta(days=7 * i)
        insert_activity(conn, 100 + i, f"{day}T07:00:00", distance_m=km * 1000, duration_s=3600)
    conn.commit()


def test_training_paces_match_the_vdot_50_table():
    p = training_paces(50.0)
    assert p["m"] == pytest.approx(4 * 60 + 31, abs=2)
    assert p["t"] == pytest.approx(4 * 60 + 15, abs=2)
    assert p["i"] == pytest.approx(3 * 60 + 55, abs=2)
    assert p["r"] * 0.4 == pytest.approx(88, abs=1)
    assert p["e_fast"] < p["e_slow"]
    assert p["e_fast"] > p["m"] > p["t"] > p["i"] > p["r"]


def test_the_current_level_comes_from_the_best_recent_race(data_dir, analysis_db, client_factory):
    (data_dir / "races.csv").write_text(HEADER + "2026-10-04,,5000,1245,yes,\n", encoding="utf-8")
    weekly_km(analysis_db, 40)

    body = plan(client_factory)

    assert body["current"]["source"] == "races"
    assert body["current"]["five_k_s"] == pytest.approx(1245, abs=1)
    assert body["target_vdot"] == pytest.approx(49.8, abs=0.05)
    assert body["feasibility"] == "stretch"
    assert body["base_km"] == 40
    assert len(body["weeks"]) == 8
    # Weeks 1-4 train at the current VDOT, weeks 5-8 one higher.
    assert body["weeks"][0]["vdot"] == pytest.approx(body["current"]["vdot"], abs=0.05)
    assert body["weeks"][4]["vdot"] == pytest.approx(body["current"]["vdot"] + 1, abs=0.05)
    assert all("races.csv" not in w and "起步" not in w for w in body["warnings"])


def test_a_typed_5k_time_overrides_races_csv(data_dir, client_factory):
    body = plan(client_factory, current_s=1205)

    assert body["current"]["source"] == "override"
    assert body["feasibility"] == "close"
    # Weeks 5-8 never train above the goal level.
    assert body["weeks"][7]["vdot"] == pytest.approx(body["target_vdot"], abs=0.05)


def test_without_a_race_the_level_is_assumed_and_says_so(data_dir, client_factory):
    body = plan(client_factory)

    assert body["current"]["source"] == "assumed"
    assert any("races.csv" in w for w in body["warnings"])
    assert any("30 km" in w for w in body["warnings"])  # no recent running either
    assert body["base_km"] == 30


def test_a_large_gap_suggests_an_interim_goal(data_dir, client_factory):
    body = plan(client_factory, current_s=25 * 60)

    assert body["feasibility"] == "far"
    assert body["interim_target_s"] < 25 * 60


@pytest.mark.parametrize("km", [30, 45, 80])
def test_without_parkrun_every_week_has_two_quality_days_within_the_caps(
    data_dir, analysis_db, client_factory, km
):
    weekly_km(analysis_db, km)
    body = plan(client_factory, current_s=21 * 60, days="1,2,3,4,5,6,7", parkrun_day=0)

    for w in body["weeks"]:
        assert sorted(s["day"] for s in w["sessions"]) == list(range(1, 8))
        assert sum(s["kind"] == "Q" for s in w["sessions"]) == 2
        for s in w["sessions"]:
            for part in s["parts"]:
                share, ceiling = CAP[part["pace"]]
                limit = (
                    w["km"] * share * 1.15
                    if ceiling is None
                    else min(w["km"] * share * 1.15, ceiling)
                )
                work = part["reps"] * part["dist_m"] / 1000
                # 2 reps is the floor even when the cap is lower.
                assert work <= limit or part["reps"] == 2 or part["dist_m"] == 2000
    assert body["weeks"][7]["sessions"][6]["kind"] == "race"


def test_by_default_saturday_is_parkrun_and_tuesday_the_quality_day(data_dir, client_factory):
    body = plan(client_factory, current_s=1250)

    assert body["days"] == [2, 3, 4, 6]
    assert body["parkrun_day"] == 6
    for w in body["weeks"]:
        by_day = {s["day"]: s for s in w["sessions"]}
        assert sorted(by_day) == list(range(1, 8))
        assert [d for d, s in by_day.items() if s["kind"] == "Q"] == [2]
        assert {by_day[d]["kind"] for d in (1, 5, 7)} == {"rest"}
        assert {by_day[d]["kind"] for d in (3, 4)} == {"E"}
        assert by_day[6]["kind"] == ("race" if w["n"] == 8 else "parkrun")
        assert by_day[6]["target_s"] > 0
        # The parkrun is the I session: no I reps midweek.
        assert all(p["pace"] != "I" for p in by_day[2]["parts"])
    goal = body["weeks"][7]["sessions"][5]
    assert goal["target_s"] == 1200
    # Weeks 1-3 aim at the current level, week 4 is a controlled run.
    assert body["weeks"][0]["sessions"][5]["target_s"] == pytest.approx(1250, abs=2)
    assert body["weeks"][3]["sessions"][5]["target_s"] > 1250


def test_the_current_level_comes_from_a_recent_parkrun(data_dir, analysis_db, client_factory):
    # TODAY is a Wednesday; 2026-10-24 and 2026-10-17 are Saturdays.
    insert_activity(analysis_db, 1, "2026-10-24T08:00:00", distance_m=5040, duration_s=1250)
    insert_activity(analysis_db, 2, "2026-10-17T08:00:00", distance_m=5040, duration_s=1300)
    insert_activity(analysis_db, 3, "2026-10-17T17:00:00", distance_m=5000, duration_s=1150)
    insert_activity(analysis_db, 4, "2026-10-21T08:00:00", distance_m=5000, duration_s=1150)
    insert_activity(analysis_db, 5, "2026-08-01T08:00:00", distance_m=5000, duration_s=1150)
    analysis_db.commit()

    body = plan(client_factory)

    assert body["current"]["source"] == "parkrun"
    assert body["current"]["basis_date"] == "2026-10-24"
    assert body["current"]["basis_time_s"] == 1250
    assert body["current"]["five_k_s"] == pytest.approx(1250 * (5000 / 5040) ** 1.06, abs=3)


def test_without_parkrun_day_the_saturday_runs_are_not_a_level(
    data_dir, analysis_db, client_factory
):
    insert_activity(analysis_db, 1, "2026-10-24T08:00:00", distance_m=5040, duration_s=1250)
    analysis_db.commit()

    body = plan(client_factory, parkrun_day=0)

    assert body["current"]["source"] == "assumed"
    assert body["weeks"][7]["sessions"][5]["kind"] == "race"  # last run day, Saturday


@pytest.mark.parametrize(("days", "parkrun_day"), [("2,6", 6), ("2,3,4", 6), ("2,3,9", 0)])
def test_unusable_run_days_are_refused(client_factory, days, parkrun_day):
    r = client_factory().get(
        "/api/plan5k", params={"today": TODAY, "days": days, "parkrun_day": parkrun_day}
    )
    assert r.status_code == 422


# The Garmin calendar names `running-push-plan` gives the plan sessions.
DAY_NAMES = ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"]
START = date(2026, 11, 2)  # the Monday after TODAY


def pushed(week: dict, session: dict) -> dict:
    day = START + timedelta(days=(week["n"] - 1) * 7 + session["day"] - 1)
    name = f"5K W{week['n']} {DAY_NAMES[session['day']]} {session['title']}"
    return {"date": day.isoformat(), "name": name, "workout_id": 1, "schedule_id": 2}


def write_push(data_dir, workouts) -> None:
    state = {"start": START.isoformat(), "pushed_at_utc": "2026-10-28T20:00:00Z"}
    (data_dir / "state").mkdir(exist_ok=True)
    (data_dir / "state" / "plan5k_push.json").write_text(
        json.dumps(state | {"workouts": workouts}, ensure_ascii=False), encoding="utf-8"
    )


def test_without_a_push_nothing_is_marked(data_dir, client_factory):
    assert plan(client_factory, current_s=1245)["push"] is None


def test_the_sessions_the_last_push_scheduled_are_marked(data_dir, client_factory):
    body = plan(client_factory, current_s=1245)
    week = body["weeks"][0]
    runs = [s for s in week["sessions"] if s["kind"] != "rest"]
    workouts = [pushed(week, s) for s in runs]
    stale = pushed(week, runs[0]) | {"name": "5K W1 周二 别的计划课"}
    unscheduled = pushed(body["weeks"][1], body["weeks"][1]["sessions"][1]) | {"schedule_id": None}
    write_push(data_dir, [*workouts, stale, unscheduled])

    push = plan(client_factory, current_s=1245)["push"]

    assert push["start"] == "2026-11-02"
    assert push["pushed_at_utc"] == "2026-10-28T20:00:00Z"
    # The stale name counts as pushed but matches no session of this plan;
    # a workout that never got a calendar date is not pushed.
    assert push["total"] == len(runs) + 1
    assert push["sessions"] == [
        {"week": 1, "day": s["day"], "date": w["date"]} for s, w in zip(runs, workouts, strict=True)
    ]


def test_a_push_with_other_run_days_matches_nothing(data_dir, client_factory):
    week = plan(client_factory, current_s=1245)["weeks"][0]
    write_push(data_dir, [pushed(week, s) for s in week["sessions"] if s["kind"] != "rest"])

    push = plan(client_factory, current_s=1245, days="1,3,5,7", parkrun_day=0)["push"]

    assert push["total"] > 0
    assert push["sessions"] == []


def test_an_unreadable_push_record_is_a_warning(data_dir, client_factory):
    (data_dir / "state").mkdir()
    (data_dir / "state" / "plan5k_push.json").write_text("{not json", encoding="utf-8")

    body = plan(client_factory, current_s=1245)

    assert body["push"] is None
    assert any("plan5k_push.json" in w for w in body["warnings"])
