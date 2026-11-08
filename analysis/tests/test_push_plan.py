"""Seam: `running-push-plan` (dry run, push, no duplicates, replace, partial
failure), with the importer's real `push()` from garmin_metrics.py driving a
fake Garmin client: nothing reaches the network."""

import importlib.util
import json
from datetime import date, timedelta

import pytest
from synthetic import insert_activity

from running.push_plan import STATE_FILE, main, next_monday, script_path

TODAY = "2026-11-08"
HEADER = "date,activity_id,distance_m,time_s,all_out,note\n"
ARGS = ["--today", TODAY, "--days", "2,3,4,6", "--parkrun", "6"]


def load_script():
    spec = importlib.util.spec_from_file_location("garmin_metrics", script_path())
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeGarmin:
    def __init__(self, fail_upload_at: int | None = None):
        self.next_id = 1000
        self.workouts: dict[int, dict] = {}
        self.calendar: dict[int, str] = {}
        self.sent = 0
        self.fail_upload_at = fail_upload_at
        self.uploads = 0

    def upload_workout(self, workout):
        self.uploads += 1
        if self.uploads == self.fail_upload_at:
            raise RuntimeError("HTTP 500")
        self.next_id += 1
        self.workouts[self.next_id] = workout
        return {"workoutId": self.next_id}

    def schedule_workout(self, workout_id, day):
        assert workout_id in self.workouts
        self.calendar[workout_id] = day
        return {"workoutScheduleId": workout_id + 50_000}

    def delete_workout(self, workout_id):
        del self.workouts[workout_id]
        self.calendar.pop(workout_id, None)

    def send_scheduled_workouts_to_devices(self):
        self.sent += 1


def fake_runner(garmin):
    script = load_script()

    def run(request, on_result):
        # Through JSON like the real pipe.
        try:
            script.push(garmin, json.loads(json.dumps(request)), on_result, lambda: None)
        except Exception:
            return 1
        return 0

    return run


@pytest.fixture
def data(data_dir, analysis_db):
    (data_dir / "races.csv").write_text(HEADER + "2026-10-04,,5000,1245,yes,\n", encoding="utf-8")
    for i in range(8):
        day = date.fromisoformat(TODAY) - timedelta(days=7 * i)
        insert_activity(analysis_db, 100 + i, f"{day}T07:00:00", distance_m=40_000, duration_s=3600)
    analysis_db.commit()
    return data_dir


def state(data_dir):
    return json.loads((data_dir / "state" / STATE_FILE).read_text(encoding="utf-8"))


def test_next_monday_is_the_coming_one():
    assert next_monday(date(2026, 11, 8)) == date(2026, 11, 9)  # Sunday
    assert next_monday(date(2026, 11, 9)) == date(2026, 11, 16)  # Monday


def test_a_dry_run_prints_the_workouts_and_sends_nothing(data, capsys):
    def never(request, on_result):
        raise AssertionError("dry run must not push")

    assert main(ARGS, runner=never) == 0

    out = capsys.readouterr().out
    assert "2026-11-10" in out and "2027-01-02" in out
    assert "共 32 个训练，2026-11-09 .. 2027-01-03" in out
    assert "热身 3 km @" in out and "×(" in out
    assert "--apply" in out
    assert not (data / "state").exists()


def test_apply_uploads_schedules_and_records_every_workout(data):
    garmin = FakeGarmin()

    assert main([*ARGS, "--apply"], runner=fake_runner(garmin)) == 0

    assert len(garmin.workouts) == 32
    assert sorted(garmin.calendar.values())[0] == "2026-11-10"
    assert garmin.sent == 1
    s = state(data)
    assert s["start"] == "2026-11-09"
    assert {w["workout_id"] for w in s["workouts"]} == set(garmin.workouts)
    assert all(w["schedule_id"] for w in s["workouts"])


def test_a_second_apply_refuses_to_create_duplicates(data, capsys):
    garmin = FakeGarmin()
    main([*ARGS, "--apply"], runner=fake_runner(garmin))

    assert main([*ARGS, "--apply"], runner=fake_runner(garmin)) == 1

    assert len(garmin.workouts) == 32
    assert "--replace" in capsys.readouterr().err


def test_replace_deletes_only_what_the_last_push_created(data):
    garmin = FakeGarmin()
    garmin.workouts[1] = {"workoutName": "the user's own workout"}
    main([*ARGS, "--apply"], runner=fake_runner(garmin))
    first = {w["workout_id"] for w in state(data)["workouts"]}

    assert main([*ARGS, "--apply", "--replace"], runner=fake_runner(garmin)) == 0

    assert 1 in garmin.workouts
    assert not first & set(garmin.workouts)
    assert len(garmin.workouts) == 33
    assert {w["workout_id"] for w in state(data)["workouts"]} == set(garmin.workouts) - {1}


def test_a_failed_push_keeps_what_was_created_so_replace_can_clean_up(data, capsys):
    garmin = FakeGarmin(fail_upload_at=5)

    assert main([*ARGS, "--apply"], runner=fake_runner(garmin)) == 1

    assert "新建并排进日历 4/32" in capsys.readouterr().err
    assert len(state(data)["workouts"]) == 4

    retry = FakeGarmin()
    retry.workouts = dict(garmin.workouts)
    retry.next_id = garmin.next_id
    assert main([*ARGS, "--apply", "--replace"], runner=fake_runner(retry)) == 0
    assert len(retry.workouts) == 32


def test_a_start_that_is_not_a_monday_is_refused(data, capsys):
    assert main([*ARGS, "--start", "2026-11-10"]) == 2
    assert "周一" in capsys.readouterr().err
