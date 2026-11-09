"""Seam: the 5K plan as Garmin structured workouts (`garmin_plan.plan_workouts`)."""

from datetime import date, timedelta

import pytest
from synthetic import insert_activity

from running.garmin_plan import PACE_BAND_S, plan_workouts, watch_note
from running.plan5k import plan_5k

TODAY = date(2026, 11, 8)  # a Sunday
START = date(2026, 11, 9)
HEADER = "date,activity_id,distance_m,time_s,all_out,note\n"


@pytest.fixture
def plan(data_dir, analysis_db):
    (data_dir / "races.csv").write_text(HEADER + "2026-10-04,,5000,1245,yes,\n", encoding="utf-8")
    for i in range(8):
        day = TODAY - timedelta(days=7 * i)
        insert_activity(analysis_db, 100 + i, f"{day}T07:00:00", distance_m=40_000, duration_s=3600)
    analysis_db.commit()
    return plan_5k(today=TODAY, days=[2, 3, 4, 6], parkrun_day=6)


def steps(w):
    return w["workout"]["workoutSegments"][0]["workoutSteps"]


def flat(step_list):
    for s in step_list:
        yield s
        yield from flat(s.get("workoutSteps", []))


def pace_of(step):
    """(slow, fast) in s/km from a pace.zone step, the order Garmin stores them."""
    return 1000 / step["targetValueOne"], 1000 / step["targetValueTwo"]


def test_every_run_day_of_the_8_weeks_becomes_one_dated_workout(plan):
    workouts = plan_workouts(plan, START)

    assert len(workouts) == 4 * 8
    assert {date.fromisoformat(w["date"]).isoweekday() for w in workouts} == {2, 3, 4, 6}
    assert workouts[0]["date"] == "2026-11-10"
    assert workouts[-1]["date"] == "2027-01-02"
    assert len({w["date"] for w in workouts}) == len(workouts)
    for w in workouts:
        assert w["workout"]["sportType"]["sportTypeKey"] == "running"
        assert w["workout"]["workoutName"].startswith(f"5K W{w['week']} ")
        assert w["workout"]["estimatedDurationInSecs"] > 0
        orders = [s["stepOrder"] for s in flat(steps(w))]
        assert orders == list(range(1, len(orders) + 1))


def test_the_start_must_be_a_monday(plan):
    with pytest.raises(ValueError, match="周一"):
        plan_workouts(plan, START + timedelta(days=1))


def test_an_easy_run_is_its_distance_at_the_weeks_e_pace(plan):
    w = next(w for w in plan_workouts(plan, START) if w["name"].endswith(" Easy"))
    week = plan["weeks"][w["week"] - 1]
    (step,) = steps(w)

    assert step["endCondition"]["conditionTypeKey"] == "distance"
    assert step["endConditionValue"] == w["km"] * 1000
    slow, fast = pace_of(step)
    assert fast == pytest.approx(week["paces"]["e_fast"], abs=0.1)
    assert slow == pytest.approx(week["paces"]["e_slow"], abs=0.1)


def test_a_quality_day_has_warmup_repeats_with_recoveries_and_cooldown(plan):
    # Week 2 with a parkrun: nx1600 m @T (1 min) + nx200 m @R (200 m jog).
    w = next(w for w in plan_workouts(plan, START) if w["week"] == 2 and "@T" in w["name"])
    paces = plan["weeks"][1]["paces"]
    session = next(s for s in plan["weeks"][1]["sessions"] if s["kind"] == "Q")
    t_part, r_part = session["parts"]
    warm, t_group, between, r_group, cool = steps(w)

    assert warm["stepType"]["stepTypeKey"] == "warmup"
    assert warm["endConditionValue"] == 3000
    assert cool["stepType"]["stepTypeKey"] == "cooldown"
    assert cool["endConditionValue"] == 2000
    assert between["endCondition"]["conditionTypeKey"] == "lap.button"

    assert t_group["type"] == "RepeatGroupDTO"
    assert t_group["numberOfIterations"] == t_part["reps"] >= 2
    assert t_group["skipLastRestStep"] is True
    work, rest = t_group["workoutSteps"]
    assert work["endConditionValue"] == 1600
    slow, fast = pace_of(work)
    assert fast == pytest.approx(paces["t"] - PACE_BAND_S, abs=0.1)
    assert slow == pytest.approx(paces["t"] + PACE_BAND_S, abs=0.1)
    assert (rest["endCondition"]["conditionTypeKey"], rest["endConditionValue"]) == ("time", 60)
    assert rest["targetType"]["workoutTargetTypeKey"] == "no.target"

    r_work, r_rest = r_group["workoutSteps"]
    assert r_group["numberOfIterations"] == r_part["reps"] >= 2
    assert r_work["endConditionValue"] == 200
    assert pace_of(r_work)[1] == pytest.approx(paces["r"] - PACE_BAND_S, abs=0.1)
    assert (r_rest["endCondition"]["conditionTypeKey"], r_rest["endConditionValue"]) == (
        "distance",
        200,
    )
    assert work["childStepId"] == t_group["childStepId"] != r_group["childStepId"]


def test_the_goal_parkrun_is_5_km_at_goal_pace_between_warmup_and_cooldown(plan):
    w = plan_workouts(plan, START)[-1]
    warm, race, cool = steps(w)

    assert w["name"] == "5K W8 Sat Goal parkrun"
    assert (warm["endConditionValue"], race["endConditionValue"], cool["endConditionValue"]) == (
        2000,
        5000,
        1500,
    )
    slow, fast = pace_of(race)
    assert (fast + slow) / 2 == pytest.approx(240, abs=0.1)  # sub-20: 4:00/km
    assert w["workout"]["description"].startswith("Even pace 4:00/km")


def watch_text(w):
    yield w["name"]
    yield w["workout"]["workoutName"]
    yield w["workout"].get("description", "")
    for step in flat(steps(w)):
        yield step.get("description", "")


@pytest.mark.parametrize(
    ("days", "parkrun_day"), [([2, 3, 4, 6], 6), ([2, 4, 6, 7], None), ([1, 3, 5, 6, 7], None)]
)
def test_everything_the_watch_shows_is_ascii(data_dir, analysis_db, days, parkrun_day):
    # Garmin watches show Chinese as garbage.
    (data_dir / "races.csv").write_text(HEADER + "2026-10-04,,5000,1245,yes,\n", encoding="utf-8")
    plan = plan_5k(today=TODAY, days=days, parkrun_day=parkrun_day)

    texts = [t for w in plan_workouts(plan, START) for t in watch_text(w)]

    assert all(t.isascii() for t in texts), [t for t in texts if not t.isascii()]


def test_volume_cap_notes_are_translated():
    note = "I 量按周跑量上限从 6 组减到 4 组；连续 T 按周跑量上限从 5 km 减到 3 km"

    assert watch_note(note) == (
        "I cut from 6 to 4 reps by the weekly volume cap; "
        "Continuous T cut from 5 km to 3 km by the weekly volume cap"
    )


def test_an_unknown_note_is_refused_rather_than_sent_in_chinese():
    with pytest.raises(ValueError, match="英文"):
        watch_note("新的说明")
