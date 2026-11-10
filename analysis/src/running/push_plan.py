"""`running-push-plan`: put the 8-week 5K plan on the Garmin Connect calendar.

Without `--apply` it only prints the plan sessions it would create (a dry
run, no network). With `--apply` it hands them to the importer's
garminconnect script (`garmin_metrics.py push`), which uploads each one as a
workout and schedules it on its date; the watch picks them up at its next
sync with Garmin Connect.

The ids Garmin returns are kept in `state/plan5k_push.json` in the data
directory, written after every finished item, so a second `--apply` refuses
to create duplicates and `--apply --replace` first deletes exactly the
workouts an earlier push created (nothing else in the Garmin account). The
file also keeps the plan settings and each workout's steps as sent, which the
dashboard's plan review (`running.plan_review`) compares the runs against.

A rate limit writes the same cooldown marker `runsync sync` writes
(`state/garminconnect.cooldown.json`, 24 hours), and a push is refused while
one is active, so neither program keeps hitting Garmin.

`push_status` tells the dashboard which sessions of a plan the last push put
on the calendar (read-only).
"""

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, TypedDict

from running.config import ConfigError, data_dir
from running.console import utf8_stdio
from running.garmin_plan import PlannedWorkout, describe, plan_workouts
from running.plan5k import (
    DEFAULT_DAYS,
    DEFAULT_PARKRUN_DAY,
    DEFAULT_TARGET_S,
    WEEKS,
    Plan5k,
    mmss,
    plan_5k,
)

STATE_FILE = "plan5k_push.json"
# The importer's names for the garminconnect source and its cooldown
# (`importer/src/cooldown.rs`, `garmin_metrics.rs`).
SOURCE = "garminconnect"
COOLDOWN_HOURS = 24
# Exit codes of garmin_metrics.py (a standalone script, so not importable).
EXIT_AUTH = 3
EXIT_RATE_LIMITED = 4
# The dashboard's bounds for the same settings (`/api/plan5k`).
MIN_TIME_S, MAX_TIME_S = 600, 3600

# Runs the push with a request and calls back once per JSON result line;
# returns the process exit code.
Runner = Callable[[dict[str, Any], Callable[[dict[str, Any]], None]], int]


def script_path() -> Path:
    return Path(__file__).resolve().parents[3] / "importer" / "garminconnect" / "garmin_metrics.py"


def week_one_start(today: date) -> date:
    """Today when it is a Monday, else the coming Monday."""
    return today + timedelta(days=(7 - today.weekday()) % 7)


def parse_time(text: str) -> float:
    """ "20:00" -> 1200.0, "1:00:00" -> 3600.0, within the dashboard's bounds."""
    try:
        parts = [float(p) for p in text.strip().split(":")]
    except ValueError:
        parts = []
    if not 2 <= len(parts) <= 3 or any(p < 0 for p in parts):
        raise argparse.ArgumentTypeError(f"时间格式应为 mm:ss：{text!r}")
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + p
    if not MIN_TIME_S <= seconds <= MAX_TIME_S:
        raise argparse.ArgumentTypeError(
            f"5K 时间应在 {mmss(MIN_TIME_S)} 到 {mmss(MAX_TIME_S)} 之间：{text!r}"
        )
    return seconds


def parse_days(text: str) -> list[int]:
    """ "2,3,4,6" -> [2, 3, 4, 6]; 1 = Monday."""
    if not re.fullmatch(r"[1-7](,[1-7])*", text.strip()):
        raise argparse.ArgumentTypeError(f"跑步日应为 1–7，用逗号分隔：{text!r}")
    return [int(d) for d in text.split(",")]


def _utc(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def load_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


class PushedSession(TypedDict):
    week: int
    day: int  # 1 = Monday
    date: str  # YYYY-MM-DD on the Garmin calendar


class PushStatus(TypedDict):
    start: str  # Monday of week 1 in the last push
    pushed_at_utc: str | None
    total: int  # plan sessions on the Garmin calendar
    sessions: list[PushedSession]  # those that are also sessions of `plan`


def push_status(plan: Plan5k, state: dict[str, Any] | None) -> PushStatus | None:
    """Which sessions of `plan` the last push scheduled: same date and name.
    A push made with other settings matches fewer (or none) of them."""
    scheduled = [w for w in (state or {}).get("workouts", []) if w.get("schedule_id")]
    if state is None or not scheduled:
        return None
    start = date.fromisoformat(state["start"])
    on_calendar = {(w["date"], w["name"]) for w in scheduled}
    sessions: list[PushedSession] = [
        {"week": w["week"], "day": w["day"], "date": w["date"]}
        for w in plan_workouts(plan, start)
        if (w["date"], w["name"]) in on_calendar
    ]
    return {
        "start": start.isoformat(),
        "pushed_at_utc": state.get("pushed_at_utc"),
        "total": len(on_calendar),
        "sessions": sessions,
    }


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".json.part")
    part.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    part.replace(path)


def cooldown_path(state_dir: Path) -> Path:
    return state_dir / f"{SOURCE}.cooldown.json"


def active_cooldown(state_dir: Path, now: datetime) -> str | None:
    """`until_utc` of the garminconnect cooldown when one is active at `now`."""
    marker = load_state(cooldown_path(state_dir))
    if marker is None:
        return None
    until = datetime.strptime(marker["until_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return marker["until_utc"] if now < until else None


def start_cooldown(state_dir: Path, now: datetime) -> str:
    until = _utc(now + timedelta(hours=COOLDOWN_HOURS))
    marker = {
        "source": SOURCE,
        "since_utc": _utc(now),
        "until_utc": until,
        "reason": f"{SOURCE}: HTTP 429 or CAPTCHA required (running-push-plan)",
    }
    save_state(cooldown_path(state_dir), marker)
    return until


def script_runner(token_dir: Path, interval: float) -> Runner:
    def run(request: dict[str, Any], on_result: Callable[[dict[str, Any]], None]) -> int:
        cmd = ["uv", "run", "--quiet", "--script", str(script_path())]
        cmd += ["push", "--token-dir", str(token_dir), "--interval", str(interval)]
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8"
        )
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(json.dumps(request, ensure_ascii=False))
        proc.stdin.close()
        for line in proc.stdout:
            if line.strip():
                on_result(json.loads(line))
        return proc.wait()

    return run


def apply(
    workouts: list[PlannedWorkout],
    start: date,
    state_dir: Path,
    runner: Runner,
    replace: bool,
    now: datetime,
    settings: dict[str, Any] | None = None,
) -> tuple[int, str]:
    """Push and keep the state file current. Returns (exit code, message)."""
    until = active_cooldown(state_dir, now)
    if until is not None:
        return EXIT_RATE_LIMITED, (
            f"Garmin 限流冷却中，到 {until}（UTC）为止不推送。"
            f"要提前恢复，删掉 state/{cooldown_path(state_dir).name}。"
        )
    state_path = state_dir / STATE_FILE
    state = load_state(state_path) or {"workouts": []}
    old = [w for w in state["workouts"] if w.get("workout_id")]
    if old and not replace:
        return 1, (
            f"之前已推送 {len(old)} 节计划课（{state.get('start')} 开始）。"
            "要换成新计划，用 --apply --replace：先删掉那些再推送。"
        )
    by_date = {w["date"]: w for w in workouts}
    state = {"start": start.isoformat(), "pushed_at_utc": _utc(now), "workouts": old}
    if settings is not None:
        state["settings"] = settings
    counts = {"deleted": 0, "created": 0}

    def on_result(result: dict[str, Any]) -> None:
        if "deleted" in result:
            state["workouts"] = [
                w for w in state["workouts"] if w["workout_id"] != result["deleted"]
            ]
            counts["deleted"] += 1
        else:
            planned = by_date[result["date"]]
            state["workouts"].append(
                {
                    "date": result["date"],
                    "name": planned["name"],
                    "workout_id": result["workout_id"],
                    "schedule_id": result["schedule_id"],
                    "workout": planned["workout"],
                }
            )
            counts["created"] += 1
        save_state(state_path, state)

    save_state(state_path, state)
    request = {
        "delete": [w["workout_id"] for w in old],
        "workouts": [{"date": w["date"], "workout": w["workout"]} for w in workouts],
    }
    code = runner(request, on_result)
    done = (
        f"删除旧计划课 {counts['deleted']} 节，"
        f"新建并排进日历 {counts['created']}/{len(workouts)} 节"
    )
    if code == 0:
        return 0, f"{done}。手表下次与 Garmin Connect 同步后会出现这些计划课。"
    if code == EXIT_RATE_LIMITED:
        until = start_cooldown(state_dir, now)
        reason = f"Garmin 限流（HTTP 429 或需要 CAPTCHA），冷却到 {until}（UTC）"
    elif code == EXIT_AUTH:
        reason = "garminconnect token 缺失或失效，先运行 `runsync login`"
    else:
        reason = "garminconnect 脚本出错，见上方信息"
    return (
        code,
        f"推送中断：{reason}。已完成：{done}。用 --apply --replace 重新推送会先删掉已建的。",
    )


def main(argv: list[str] | None = None, runner: Runner | None = None) -> int:
    utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="running-push-plan",
        description="把 8 周 5K 计划推送到 Garmin Connect 日历（默认只预览）。",
    )
    parser.add_argument(
        "--start", type=date.fromisoformat, help="第 1 周的周一，默认本周一（今天是周一时）或下周一"
    )
    parser.add_argument("--target", type=parse_time, default=float(DEFAULT_TARGET_S))
    parser.add_argument("--current", type=parse_time, help="当前 5K 成绩，留空按比赛/parkrun")
    parser.add_argument(
        "--days",
        type=parse_days,
        default=list(DEFAULT_DAYS),
        help="跑步日，1 = 周一，例如 2,3,4,6",
    )
    parser.add_argument(
        "--parkrun", type=int, choices=range(8), default=DEFAULT_PARKRUN_DAY, help="0 = 没有"
    )
    parser.add_argument("--today", type=date.fromisoformat, help=argparse.SUPPRESS)
    parser.add_argument("--apply", action="store_true", help="真正上传并排进日历")
    parser.add_argument("--replace", action="store_true", help="先删掉上次推送的计划课")
    parser.add_argument("--interval", type=float, default=2.0, help="请求间隔（秒）")
    args = parser.parse_args(argv)

    today = args.today or date.today()
    start = args.start or week_one_start(today)
    if start < today:
        print(f"开始日期 {start} 已经过去，用 --start 指定今天以后的周一", file=sys.stderr)
        return 2
    try:
        plan = plan_5k(
            today=today,
            target_s=args.target,
            current_s=args.current,
            days=args.days,
            parkrun_day=args.parkrun or None,
        )
        workouts = plan_workouts(plan, start)
        root = data_dir()
    except (ValueError, ConfigError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 2

    current = plan["current"]
    end = start + timedelta(days=7 * WEEKS - 1)
    print(
        f"目标 5K {mmss(plan['target_s'])}（VDOT {plan['target_vdot']}），"
        f"当前 VDOT {current['vdot']:.1f}（{current['source']}），基础周量 {plan['base_km']:g} km"
    )
    print(f"第 1 周从 {start}（周一）开始，到 {end}；要换开始日期用 --start")
    for warning in plan["warnings"]:
        print(f"注意：{warning}")
    for w in workouts:
        print(f"{w['date']}  {w['km']:>4g} km  {w['name']}")
        print(f"            {describe(w['workout'])}")
    print(f"共 {len(workouts)} 节计划课，{start} .. {end}")
    if not args.apply:
        print("这是预览，没有上传。确认后加 --apply 推送到 Garmin Connect。")
        return 0

    token_dir = root / "secrets" / "garminconnect"
    if runner is None:
        if not token_dir.is_dir():
            print("没有 garminconnect token：先运行 `runsync login`", file=sys.stderr)
            return EXIT_AUTH
        runner = script_runner(token_dir, args.interval)
    now = datetime.now(UTC)
    settings = {
        "today": plan["today"],
        "target_s": args.target,
        "current_s": args.current,
        "days": plan["days"],
        "parkrun_day": plan["parkrun_day"],
    }
    code, message = apply(workouts, start, root / "state", runner, args.replace, now, settings)
    print(message, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
