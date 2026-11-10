"""Seam: `running-push-plan` (dry run, push, no duplicates, replace, partial
failure, cooldown), with the importer's real `push()` from garmin_metrics.py
driving a fake Garmin client: nothing reaches the network. One test runs the
script's `push` command itself with a stub garminconnect package."""

import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta

import pytest
from synthetic import insert_activity

from running.push_plan import STATE_FILE, main, script_path, week_one_start

TODAY = "2026-11-08"
HEADER = "date,activity_id,distance_m,time_s,all_out,note\n"
ARGS = ["--today", TODAY, "--days", "2,3,4,6", "--parkrun", "6"]


def load_script():
    spec = importlib.util.spec_from_file_location("garmin_metrics", script_path())
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HttpError(Exception):
    """Like garminconnect's errors: the HTTP response is attached."""

    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.response = type("Response", (), {"status_code": status})()


class FakeGarmin:
    def __init__(self, fail_upload_at: int | None = None, fail_status: int = 500):
        self.next_id = 1000
        self.workouts: dict[int, dict] = {}
        self.calendar: dict[int, str] = {}
        self.sent = 0
        self.fail_upload_at = fail_upload_at
        self.fail_status = fail_status
        self.uploads = 0

    def upload_workout(self, workout):
        self.uploads += 1
        if self.uploads == self.fail_upload_at:
            raise HttpError(self.fail_status)
        self.next_id += 1
        self.workouts[self.next_id] = workout
        return {"workoutId": self.next_id}

    def schedule_workout(self, workout_id, day):
        assert workout_id in self.workouts
        self.calendar[workout_id] = day
        return {"workoutScheduleId": workout_id + 50_000}

    def delete_workout(self, workout_id):
        if workout_id not in self.workouts:
            raise HttpError(404)
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
        except Exception as err:
            return script.report_error(err)
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


def cooldown(data_dir):
    return data_dir / "state" / "garminconnect.cooldown.json"


def test_week_one_starts_today_on_a_monday_else_the_coming_monday():
    assert week_one_start(date(2026, 11, 8)) == date(2026, 11, 9)  # Sunday
    assert week_one_start(date(2026, 11, 9)) == date(2026, 11, 9)  # Monday
    assert week_one_start(date(2026, 11, 10)) == date(2026, 11, 16)  # Tuesday


def test_a_dry_run_prints_the_workouts_and_sends_nothing(data, capsys):
    def never(request, on_result):
        raise AssertionError("dry run must not push")

    assert main(ARGS, runner=never) == 0

    out = capsys.readouterr().out
    assert "2026-11-10" in out and "2027-01-02" in out
    assert "第 1 周从 2026-11-09（周一）开始" in out
    assert "共 32 节计划课，2026-11-09 .. 2027-01-03" in out
    assert "Warmup 3 km @" in out and "x(" in out and "Cooldown 2 km @" in out
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
    assert s["settings"]["today"] == TODAY and s["settings"]["days"] == [2, 3, 4, 6]
    assert all(w["workout"]["workoutName"] == w["name"] for w in s["workouts"])


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


def test_a_workout_already_deleted_in_the_app_counts_as_deleted(data):
    garmin = FakeGarmin()
    main([*ARGS, "--apply"], runner=fake_runner(garmin))
    gone = state(data)["workouts"][0]["workout_id"]
    del garmin.workouts[gone]

    assert main([*ARGS, "--apply", "--replace"], runner=fake_runner(garmin)) == 0

    assert len(garmin.workouts) == 32


def test_a_rate_limit_writes_the_cooldown_marker_and_blocks_the_next_push(data, capsys):
    assert main([*ARGS, "--apply"], runner=fake_runner(FakeGarmin(3, fail_status=429))) == 4

    marker = json.loads(cooldown(data).read_text(encoding="utf-8"))
    assert marker["source"] == "garminconnect"
    until = datetime.strptime(marker["until_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert timedelta(hours=23) < until - datetime.now(UTC) <= timedelta(hours=24)
    capsys.readouterr()

    def never(request, on_result):
        raise AssertionError("must not push during a cooldown")

    assert main([*ARGS, "--apply", "--replace"], runner=never) == 4
    assert "冷却" in capsys.readouterr().err


def test_an_expired_cooldown_does_not_block(data):
    cooldown(data).parent.mkdir(parents=True)
    marker = {"source": "garminconnect", "since_utc": "2026-01-01T00:00:00Z"}
    marker |= {"until_utc": "2026-01-02T00:00:00Z", "reason": "old"}
    cooldown(data).write_text(json.dumps(marker), encoding="utf-8")

    assert main([*ARGS, "--apply"], runner=fake_runner(FakeGarmin())) == 0


@pytest.mark.parametrize(
    "args",
    [["--target", "5:00"], ["--current", "2:00:00"], ["--days", "2,8"], ["--parkrun", "9"]],
)
def test_settings_outside_the_dashboard_bounds_are_refused(data, args):
    with pytest.raises(SystemExit) as exit_info:
        main([*ARGS, *args])
    assert exit_info.value.code == 2


STUB = """
class Garmin:
    def login(self, token_dir):
        pass

    def upload_workout(self, workout):
        print(workout["workoutName"], file=open(NAMES, "a", encoding="utf-8"))
        return {"workoutId": 7}

    def schedule_workout(self, workout_id, day):
        return {"workoutScheduleId": 8}

    def send_scheduled_workouts_to_devices(self):
        pass
"""


def test_the_push_command_reads_chinese_names_whatever_the_console_code_page(tmp_path):
    stub = tmp_path / "stub" / "garminconnect"
    stub.mkdir(parents=True)
    names = tmp_path / "names.txt"
    (stub / "__init__.py").write_text(f"NAMES = {str(names)!r}\n{STUB}", encoding="utf-8")
    token_dir = tmp_path / "token"
    token_dir.mkdir()
    (token_dir / "garmin_tokens.json").write_text("{}", encoding="utf-8")
    name = "5K W1 周二 轻松跑"
    request = {"workouts": [{"date": "2026-11-10", "workout": {"workoutName": name}}]}
    env = os.environ | {"PYTHONPATH": str(stub.parent), "PYTHONIOENCODING": "cp1252"}

    proc = subprocess.run(
        [sys.executable, str(script_path()), "push", "--token-dir", str(token_dir)],
        input=json.dumps(request, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        env=env,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert names.read_text(encoding="utf-8").strip() == name
    result = json.loads(proc.stdout)
    assert result == {"date": "2026-11-10", "workout_id": 7, "schedule_id": 8}
