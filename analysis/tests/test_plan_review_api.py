"""Seam: GET /api/plan-review, the review of every pushed 5K plan session
against the run of its day. The state file and the per-second records are
synthetic; one test pushes the real plan through a fake Garmin client."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from synthetic import insert_activity
from test_push_plan import ARGS, FakeGarmin, fake_runner
from test_push_plan import data as data  # noqa: F401  (fixture)

from running.push_plan import STATE_FILE, main

TODAY = "2026-11-15"
E = (390.0, 350.0)  # slow, fast s/km
T = (270.0, 262.0)
RACE = (252.0, 246.0)  # 5 km in 20:45 at the middle


def target(step: dict, pace: tuple[float, float]) -> dict:
    return step | {
        "targetType": {"workoutTargetTypeKey": "pace.zone"},
        "targetValueOne": 1000 / pace[0],
        "targetValueTwo": 1000 / pace[1],
    }


def step(key: str, metres: float, pace: tuple[float, float]) -> dict:
    return target(
        {
            "type": "ExecutableStepDTO",
            "stepType": {"stepTypeKey": key},
            "endCondition": {"conditionTypeKey": "distance"},
            "endConditionValue": metres,
        },
        pace,
    )


def repeat(n: int, metres: float, pace: tuple[float, float], rest_s: float) -> dict:
    rest = {
        "type": "ExecutableStepDTO",
        "stepType": {"stepTypeKey": "recovery"},
        "endCondition": {"conditionTypeKey": "time"},
        "endConditionValue": rest_s,
    }
    return {
        "type": "RepeatGroupDTO",
        "numberOfIterations": n,
        "workoutSteps": [step("interval", metres, pace), rest],
    }


def workout(*steps: dict) -> dict:
    return {"workoutSegments": [{"workoutSteps": list(steps)}]}


SESSIONS = [
    (
        "2026-11-10",
        "5K W1 Tue 2x1.6km @T",
        workout(step("warmup", 2000, E), repeat(2, 1600, T, 60), step("cooldown", 2000, E)),
    ),
    ("2026-11-11", "5K W1 Wed Easy", workout(step("interval", 6000, E))),
    ("2026-11-12", "5K W1 Thu Easy", workout(step("interval", 5000, E))),
    (
        "2026-11-14",
        "5K W1 Sat parkrun all-out",
        workout(step("warmup", 1000, E), step("interval", 5000, RACE), step("cooldown", 1000, E)),
    ),
    ("2026-11-15", "5K W1 Sun Long run", workout(step("interval", 10000, E))),
    ("2026-11-17", "5K W2 Tue 5x1km @I", workout(step("warmup", 2000, E))),
]


def write_state(data_dir, sessions=SESSIONS, with_steps=True):
    workouts = []
    for i, (day, name, w) in enumerate(sessions):
        entry = {"date": day, "name": name, "workout_id": 1000 + i, "schedule_id": 5000 + i}
        if with_steps:
            entry["workout"] = w
        workouts.append(entry)
    state = {"start": "2026-11-09", "pushed_at_utc": "2026-11-08T20:00:00Z", "workouts": workouts}
    (data_dir / "state").mkdir(exist_ok=True)
    (data_dir / "state" / STATE_FILE).write_text(json.dumps(state), encoding="utf-8")


def add_records(conn, activity_id: int, start_utc: str, segments) -> float:
    """1 Hz records from (seconds, m/s, heart rate[, single-foot cadence])
    segments; cadence defaults to 85 (170 spm). Returns metres."""
    t = datetime.strptime(start_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    dist, rows = 0.0, []
    for seconds, speed, hr, *cad in segments:
        for _ in range(int(seconds)):
            t += timedelta(seconds=1)
            dist += speed
            ts = t.strftime("%Y-%m-%dT%H:%M:%SZ")
            rows.append((activity_id, ts, hr, speed, cad[0] if cad else 85.0, dist))
    conn.executemany(
        "INSERT INTO records (activity_id, timestamp, heart_rate, speed, cadence, distance)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    return dist


def add_run(conn, activity_id: int, day: str, segments) -> None:
    secs = sum(seg[0] for seg in segments)
    metres = sum(seg[0] * seg[1] for seg in segments)
    start = insert_activity(
        conn, activity_id, f"{day}T07:00:00", distance_m=metres, duration_s=secs, avg_hr_bpm=150
    )
    add_records(conn, activity_id, start, segments)


REP_S = round(1600 / (1000 / 266))  # 1600 m at 4:26/km, inside 4:22-4:30


@pytest.fixture
def runs(data_dir, analysis_db):
    # Quality: short warm-up, both reps on pace, cool-down cut short.
    add_run(
        analysis_db,
        1,
        "2026-11-10",
        [(300, 3.0, 135, 82), (REP_S, 1000 / 266, 160, 90), (60, 2.0, 140, 80)]
        + [(REP_S, 1000 / 266, 165, 92), (100, 3.0, 145, 82)],
    )
    # Easy at 6:10/km; 11-12 missed.
    insert_activity(
        analysis_db, 2, "2026-11-11T07:00:00", distance_m=6000, duration_s=2220, avg_hr_bpm=138
    )
    # parkrun: a short warm-up, 5 km at 4:08/km, no cool-down.
    add_run(analysis_db, 3, "2026-11-14", [(300, 3.0, 140), (1240, 5000 / 1240, 175)])
    analysis_db.commit()
    write_state(data_dir)
    return data_dir


def review(client_factory, today=TODAY):
    res = client_factory().get("/api/plan-review", params={"today": today})
    assert res.status_code == 200
    return res.json()


def by_date(body):
    return {s["date"]: s for s in body["sessions"]}


def test_statuses_follow_the_runs_and_today(runs, client_factory):
    body = review(client_factory)

    status = {d: s["status"] for d, s in by_date(body).items()}
    assert status == {
        "2026-11-10": "done",
        "2026-11-11": "done",
        "2026-11-12": "missed",
        "2026-11-14": "done",
        "2026-11-15": "today",
        "2026-11-17": "upcoming",
    }
    assert body["start"] == "2026-11-09" and not body["rebuilt"] and body["warnings"] == []
    assert by_date(body)["2026-11-17"]["week"] == 2
    t = body["totals"]
    assert (t["sessions"], t["past"], t["done"], t["missed"]) == (6, 4, 3, 1)
    assert (t["quality_done"], t["quality_on_pace"]) == (1, 1)


def test_quality_reps_are_found_and_judged_against_their_range(runs, client_factory):
    s = by_date(review(client_factory))["2026-11-10"]

    assert s["planned"]["kind"] == "quality"
    reps = s["actual"]["reps"]
    assert [(r["part"], r["n"], r["verdict"]) for r in reps] == [(0, 1, "ok"), (0, 2, "ok")]
    for r in reps:
        assert r["dist_m"] == pytest.approx(1600, abs=40)
        assert r["pace"] == pytest.approx(266, abs=4)
    assert reps[1]["rest_s"] == pytest.approx(60, abs=12)
    assert reps[1]["hr_avg"] > reps[0]["hr_avg"]
    assert s["verdict"] == "good"


def test_cadence_and_stride_come_with_each_rep_split_and_run(runs, client_factory):
    sessions = by_date(review(client_factory))

    reps = sessions["2026-11-10"]["actual"]["reps"]
    assert [round(r["cadence_spm"]) for r in reps] == [180, 184]
    for r, spm in zip(reps, (180, 184), strict=True):
        assert r["stride_m"] == pytest.approx(1000 / 266 * 60 / spm, abs=0.02)
    whole = sessions["2026-11-10"]["actual"]
    assert 164 < whole["cadence_spm"] < 184
    assert whole["stride_m"] == pytest.approx(
        whole["dist_m"] / (whole["cadence_spm"] / 60 * whole["time_s"]), abs=0.02
    )
    effort = sessions["2026-11-14"]["actual"]["effort"]
    assert effort["cadence_spm"] == pytest.approx(170, abs=0.5)
    assert effort["stride_m"] == pytest.approx(5000 / 1240 * 60 / 170, abs=0.02)
    assert all(sp["cadence_spm"] == pytest.approx(170, abs=0.5) for sp in effort["splits"])
    assert all(sp["stride_m"] > 1.3 for sp in effort["splits"])
    easy = sessions["2026-11-11"]["actual"]
    assert easy["cadence_spm"] is None and easy["stride_m"] is None


def test_a_cut_warmup_and_cooldown_is_neutral_not_a_failure(runs, client_factory):
    sessions = by_date(review(client_factory))

    for day in ("2026-11-10", "2026-11-14"):
        s = sessions[day]
        warm = [n for n in s["notes"] if "热身" in n["text"]]
        assert len(warm) == 1 and warm[0]["verdict"] == "neutral"
        assert "不算未完成" in warm[0]["text"]
        assert s["verdict"] == "good"
    quality = sessions["2026-11-10"]["actual"]
    assert quality["warmup_m"] == pytest.approx(900, abs=40)
    assert quality["cooldown_m"] == pytest.approx(300, abs=40)
    assert sessions["2026-11-14"]["actual"]["cooldown_m"] == pytest.approx(0, abs=20)


def test_a_parkrun_is_judged_on_its_fastest_5k(runs, client_factory):
    s = by_date(review(client_factory))["2026-11-14"]

    assert s["planned"]["kind"] == "race"
    assert s["planned"]["target_s"] == pytest.approx(1245)
    e = s["actual"]["effort"]
    assert e["full"] and e["time_s"] == pytest.approx(1240, abs=2)
    assert len(e["splits"]) == 5
    assert e["start_m"] == pytest.approx(900, abs=20)
    assert [n["verdict"] for n in s["notes"]][:2] == ["good", "good"]


def test_an_easy_run_is_judged_on_distance_and_pace(runs, client_factory):
    s = by_date(review(client_factory))["2026-11-11"]

    assert s["planned"]["kind"] == "easy"
    assert s["actual"]["pace"] == pytest.approx(370)
    assert s["verdict"] == "good"
    assert "计划 6.0 km" in s["notes"][0]["text"]


def test_a_quality_session_without_fast_reps_needs_a_look(data_dir, analysis_db, client_factory):
    add_run(analysis_db, 1, "2026-11-10", [(1800, 3.0, 140)])
    analysis_db.commit()
    write_state(data_dir)

    s = by_date(review(client_factory))["2026-11-10"]

    assert s["actual"]["reps"] == [] and s["verdict"] == "watch"


def test_without_a_push_the_page_says_how_to_get_one(data_dir, analysis_db, client_factory):
    body = review(client_factory)

    assert body["sessions"] == [] and body["totals"] is None
    assert "running-push-plan --apply" in body["warnings"][0]


def test_an_old_push_without_steps_is_rebuilt_from_its_date(data, client_factory):  # noqa: F811
    main([*ARGS, "--apply"], runner=fake_runner(FakeGarmin()))
    path = data / "state" / STATE_FILE
    state = json.loads(path.read_text(encoding="utf-8"))
    stored = review(client_factory, "2026-11-20")
    for w in state["workouts"]:
        del w["workout"]
    path.write_text(json.dumps(state), encoding="utf-8")

    rebuilt = review(client_factory, "2026-11-20")

    assert rebuilt["rebuilt"] and "旧版推送" in rebuilt["warnings"][0]
    assert len(rebuilt["warnings"]) == 1
    assert [s["planned"] for s in rebuilt["sessions"]] == [s["planned"] for s in stored["sessions"]]
