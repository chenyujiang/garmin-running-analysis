"""The 5K plan (`plan5k.plan_5k`) as Garmin Connect structured workouts.

Each run day of the 8 weeks becomes one running workout, dated from a start
Monday, in the JSON shape `POST /workout-service/workout` takes (the same
shape `garminconnect.workout` builds):

- E and long runs: one distance step at the week's E pace range.
- Quality days: warm-up (`WARMUP_KM`) at E, then each part either as a
  repeat group (work at the part's pace, recovery ending on the part's
  `rest_end`/`rest_value`: a time or a distance, the last recovery skipped)
  or as one step, a lap-button jog between parts, cool-down (`COOLDOWN_KM`).
- parkrun and race days: warm-up, 5 km at the session's target time, cool-down.

Paces are ranges: E from the slow to the fast end of the week's E pace, the
others the plan's pace plus or minus `PACE_BAND_S` seconds per km. Garmin
stores a pace range as speeds in m/s, the slower one first.

`describe` renders a workout as one line for the preview.

Pure: nothing here reads the database or talks to Garmin.
"""

from datetime import date, timedelta
from typing import Any, TypedDict

from running.plan5k import (
    COOLDOWN_KM,
    FIVE_K,
    PARKRUN_CD_KM,
    PARKRUN_WU_KM,
    WARMUP_KM,
    Paces,
    Part,
    Plan5k,
    Session,
    mmss,
)

PACE_BAND_S = 5.0  # s/km either side of a single pace
DAY_NAMES = ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"]
NAME_PREFIX = "5K"

_RUNNING = {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1}
_STEP = {
    "warmup": {"stepTypeId": 1, "stepTypeKey": "warmup", "displayOrder": 1},
    "cooldown": {"stepTypeId": 2, "stepTypeKey": "cooldown", "displayOrder": 2},
    "interval": {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},
    "recovery": {"stepTypeId": 4, "stepTypeKey": "recovery", "displayOrder": 4},
    "repeat": {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
}
_END = {
    "lap.button": {"conditionTypeId": 1, "conditionTypeKey": "lap.button", "displayOrder": 1},
    "time": {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2},
    "distance": {"conditionTypeId": 3, "conditionTypeKey": "distance", "displayOrder": 3},
    "iterations": {"conditionTypeId": 7, "conditionTypeKey": "iterations", "displayOrder": 7},
}
_NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
_PACE_TARGET = {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone", "displayOrder": 6}

# Recovery jog pace for the duration estimate only (no target on the watch).
_JOG_FACTOR = 1.1  # times the slow end of E


class PlannedWorkout(TypedDict):
    date: str  # YYYY-MM-DD
    week: int
    day: int  # 1 = Monday
    km: float
    name: str
    workout: dict[str, Any]


PaceRange = tuple[float, float]  # (slow, fast) in s/km


def _range(paces: Paces, key: str) -> PaceRange:
    if key == "E":
        return paces["e_slow"], paces["e_fast"]
    centre = {"M": paces["m"], "T": paces["t"], "I": paces["i"], "R": paces["r"]}[key]
    return _band(centre)


def _band(pace: float) -> PaceRange:
    """A single pace as a range of `PACE_BAND_S` either side."""
    return pace + PACE_BAND_S, pace - PACE_BAND_S


class _Builder:
    """Numbers steps in order, as Garmin does, and sums the duration."""

    def __init__(self, jog_pace: float) -> None:
        self.order = 0
        self.child = 0
        self.seconds = 0.0
        self.jog_pace = jog_pace

    def step(
        self,
        kind: str,
        end: str,
        value: float | None,
        pace: PaceRange | None,
        description: str = "",
        child: int | None = None,
        times: int = 1,
    ) -> dict[str, Any]:
        self.order += 1
        step: dict[str, Any] = {
            "type": "ExecutableStepDTO",
            "stepOrder": self.order,
            "stepType": _STEP[kind],
            "endCondition": _END[end],
        }
        if value is not None:
            step["endConditionValue"] = float(value)
        if pace is None:
            step["targetType"] = _NO_TARGET
        else:
            slow, fast = pace
            step["targetType"] = _PACE_TARGET
            step["targetValueOne"] = round(1000.0 / slow, 4)
            step["targetValueTwo"] = round(1000.0 / fast, 4)
        if child is not None:
            step["childStepId"] = child
        if description:
            step["description"] = description
        per_km = self.jog_pace if pace is None else (pace[0] + pace[1]) / 2
        if end == "distance" and value is not None:
            self.seconds += times * value / 1000 * per_km
        elif end == "time" and value is not None:
            self.seconds += times * value
        return step

    def repeat(self, part: Part, pace: PaceRange) -> dict[str, Any]:
        self.order += 1
        self.child += 1
        group: dict[str, Any] = {
            "type": "RepeatGroupDTO",
            "stepOrder": self.order,
            "stepType": _STEP["repeat"],
            "childStepId": self.child,
            "numberOfIterations": part["reps"],
            "endCondition": _END["iterations"],
            "endConditionValue": float(part["reps"]),
            "smartRepeat": False,
            "skipLastRestStep": True,
        }
        work = self.step(
            "interval", "distance", part["dist_m"], pace, child=self.child, times=part["reps"]
        )
        rest = self.step(
            "recovery",
            part["rest_end"] or "lap.button",
            part["rest_value"],
            None,
            part["rest"],
            child=self.child,
            times=part["reps"] - 1,
        )
        group["workoutSteps"] = [work, rest]
        return group


def _steps(
    session: Session, paces: Paces, parkrun_day: int | None
) -> tuple[list[dict[str, Any]], float]:
    b = _Builder(paces["e_slow"] * _JOG_FACTOR)
    easy = _range(paces, "E")
    steps: list[dict[str, Any]] = []
    kind = session["kind"]
    if kind in ("E", "L"):
        steps.append(b.step("interval", "distance", session["km"] * 1000, easy))
    elif kind == "Q":
        steps.append(b.step("warmup", "distance", WARMUP_KM * 1000, easy))
        for i, part in enumerate(session["parts"]):
            if i > 0:
                steps.append(b.step("recovery", "lap.button", None, None, "慢跑恢复，准备好按圈"))
            pace = _range(paces, part["pace"])
            if part["reps"] > 1:
                steps.append(b.repeat(part, pace))
            else:
                steps.append(b.step("interval", "distance", part["dist_m"], pace))
        steps.append(b.step("cooldown", "distance", COOLDOWN_KM * 1000, easy))
    elif kind in ("parkrun", "race"):
        # The goal race is a parkrun when the plan has a parkrun day.
        parkrun = kind == "parkrun" or session["day"] == parkrun_day
        warm, cool = (PARKRUN_WU_KM, PARKRUN_CD_KM) if parkrun else (WARMUP_KM, COOLDOWN_KM)
        target = session["target_s"] or paces["five_k_s"]
        steps.append(b.step("warmup", "distance", warm * 1000, easy))
        steps.append(b.step("interval", "distance", FIVE_K, _band(target / 5), session["title"]))
        steps.append(b.step("cooldown", "distance", cool * 1000, easy))
    else:
        raise ValueError(f"不能转换的课程类型：{kind}")
    return steps, b.seconds


def plan_workouts(plan: Plan5k, start: date) -> list[PlannedWorkout]:
    """One workout per run day; week 1 starts on `start`, which must be a Monday."""
    if start.isoweekday() != 1:
        raise ValueError(f"开始日期必须是周一：{start.isoformat()}")
    out: list[PlannedWorkout] = []
    for week in plan["weeks"]:
        for session in week["sessions"]:
            if session["kind"] == "rest":
                continue
            day = start + timedelta(days=(week["n"] - 1) * 7 + session["day"] - 1)
            steps, seconds = _steps(session, week["paces"], plan["parkrun_day"])
            name = f"{NAME_PREFIX} W{week['n']} {DAY_NAMES[session['day']]} {session['title']}"
            workout: dict[str, Any] = {
                "workoutName": name,
                "sportType": _RUNNING,
                "estimatedDurationInSecs": round(seconds),
                "workoutSegments": [
                    {"segmentOrder": 1, "sportType": _RUNNING, "workoutSteps": steps}
                ],
            }
            if session["note"]:
                workout["description"] = session["note"]
            out.append(
                {
                    "date": day.isoformat(),
                    "week": week["n"],
                    "day": session["day"],
                    "km": session["km"],
                    "name": name,
                    "workout": workout,
                }
            )
    return out


def _pace_text(step: dict[str, Any]) -> str:
    if step["targetType"]["workoutTargetTypeKey"] != "pace.zone":
        return ""
    slow, fast = 1000 / step["targetValueOne"], 1000 / step["targetValueTwo"]
    return f" @{mmss(fast)}–{mmss(slow)}"


def _end_text(step: dict[str, Any]) -> str:
    key, value = step["endCondition"]["conditionTypeKey"], step.get("endConditionValue")
    if key == "distance":
        return f"{value / 1000:g} km" if value >= 1000 else f"{value:g} m"
    if key == "time":
        return f"{value / 60:g} 分钟"
    return "按圈结束"


_LABEL = {"warmup": "热身", "cooldown": "放松", "interval": "", "recovery": "恢复"}


def describe(workout: dict[str, Any]) -> str:
    """One line per workout: "热身 3 km @… → 5×(1 km @… / 3 分钟) → 放松 2 km @…"."""

    def one(step: dict[str, Any]) -> str:
        if step["type"] == "RepeatGroupDTO":
            inner = " / ".join(one(s) for s in step["workoutSteps"])
            return f"{step['numberOfIterations']}×({inner})"
        label = _LABEL[step["stepType"]["stepTypeKey"]]
        text = f"{_end_text(step)}{_pace_text(step)}"
        return f"{label} {text}" if label else text

    return " → ".join(one(s) for s in workout["workoutSegments"][0]["workoutSteps"])
