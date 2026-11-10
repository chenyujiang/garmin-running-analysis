"""Plan review: each pushed 5K plan session against the run done that day.

The plan is what the last `running-push-plan --apply` put on the Garmin
calendar (`state/plan5k_push.json`): every scheduled workout with the steps
the watch got. A push from before the file kept the steps is rebuilt from
its settings (or the defaults) and its push date; only sessions whose date
and name match the rebuilt plan get steps.

The run of a session is the longest running activity on its local date.

What is judged, per kind of session:
- Quality (warm-up, work parts, cool-down): the work reps are found in the
  per-second records as stretches faster than halfway between the E pace and
  the slowest work pace, then given to the plan's parts in order. Each rep's
  pace is checked against its range. Warm-up and cool-down are reported but
  never count against the session: they are the first thing cut when time
  is short.
- parkrun / race: the fastest continuous 5 km of the run against the planned
  time, and the first km against the average. A run shorter than 5 km is
  judged as it is. Warm-up and cool-down as above.
- Easy and long runs: distance against the plan, pace against the E range
  (faster is the only thing flagged).

`review_session` is pure (planned steps plus per-second samples);
`plan_review` reads the state file and the database.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal, TypedDict

from running.aerobic import load_records
from running.config import RunWalk
from running.db import open_analysis_db
from running.garmin_plan import plan_workouts
from running.plan5k import DEFAULT_DAYS, DEFAULT_PARKRUN_DAY, DEFAULT_TARGET_S, mmss, plan_5k
from running.push_plan import STATE_FILE, load_state
from running.runwalk import RUNNING_TYPES, classify_records
from running.section import Method, section_inputs

Kind = Literal["quality", "race", "easy", "long"]
Status = Literal["done", "missed", "today", "upcoming"]
Verdict = Literal["good", "neutral", "watch"]

FIVE_K = 5000.0
SMOOTH_HALF_S = 5  # samples either side of the smoothed speed (1 Hz records)
MERGE_GAP_S = 8.0  # fast stretches closer than this are one rep
MIN_REP_SHARE = 0.4  # a stretch shorter than this share of the shortest rep is noise
MIN_REP_S = 15.0
PACE_TOLERANCE_S = 1.0  # s/km outside a range before a rep is fast or slow
FIRST_KM_FAST_S = 5.0  # first km this much faster than the 5 km average: too fast
EASY_FAST_S = 5.0  # E run this much faster than the fast end of E: too fast
SHORT_WARMUP_M = 1000.0
PACE_BAND = 5.0  # s/km: a parkrun within this of the planned pace is on target


class PacePlan(TypedDict):
    dist_m: float
    slow: float  # s/km
    fast: float


class PartPlan(PacePlan):
    reps: int
    rest: str  # "1 min", "200 m", "" for one rep


class Planned(TypedDict):
    kind: Kind
    warmup: PacePlan | None
    parts: list[PartPlan]
    cooldown: PacePlan | None
    target_s: float | None  # parkrun / race: planned 5 km time
    km: float  # planned distance, recoveries by time not counted


class Rep(TypedDict):
    part: int | None  # index in `parts`, None for an extra rep
    n: int  # rep number within the part, from 1
    dist_m: float
    time_s: float
    pace: float  # s/km
    hr_avg: float | None
    hr_max: float | None
    rest_s: float | None  # recovery before this rep (None for the first)
    verdict: Literal["ok", "fast", "slow", "extra"]
    off_s: float  # s/km outside the range (0 inside)
    start_m: float  # distance into the run where the rep starts


class Split(TypedDict):
    km: int
    time_s: float
    hr_avg: float | None


class Effort(TypedDict):
    dist_m: float
    time_s: float
    pace: float
    hr_avg: float | None
    hr_max: float | None
    splits: list[Split]
    full: bool  # a whole 5 km
    start_m: float


class Note(TypedDict):
    verdict: Verdict
    text: str


class Actual(TypedDict):
    activity_id: int
    start_time_local: str
    activity_type: str
    dist_m: float
    time_s: float  # moving time
    pace: float | None
    hr_avg: float | None
    others: int  # other running activities that day
    warmup_m: float | None
    cooldown_m: float | None
    reps: list[Rep]
    effort: Effort | None


class SessionReview(TypedDict):
    date: str
    week: int | None
    name: str
    status: Status
    planned: Planned | None
    actual: Actual | None
    notes: list[Note]
    verdict: Verdict | None  # worst note, None when not run yet


class Totals(TypedDict):
    sessions: int
    past: int  # sessions before today, plus today's when run
    done: int
    missed: int
    quality_done: int
    quality_on_pace: int  # every rep inside its range
    planned_km: float  # of the past sessions
    done_km: float


class PlanReview(TypedDict):
    today: str
    start: str | None
    pushed_at_utc: str | None
    rebuilt: bool  # steps rebuilt from settings, not read from the state file
    sessions: list[SessionReview]
    totals: Totals | None
    warnings: list[str]
    method: Method


# --- planned steps -------------------------------------------------------------


def _pace_range(step: dict[str, Any]) -> tuple[float, float] | None:
    if step.get("targetType", {}).get("workoutTargetTypeKey") != "pace.zone":
        return None
    return 1000.0 / step["targetValueOne"], 1000.0 / step["targetValueTwo"]


def _pace_plan(step: dict[str, Any]) -> PacePlan | None:
    rng = _pace_range(step)
    if rng is None or step["endCondition"]["conditionTypeKey"] != "distance":
        return None
    return {"dist_m": float(step["endConditionValue"]), "slow": rng[0], "fast": rng[1]}


def _rest_text(step: dict[str, Any] | None) -> str:
    if step is None:
        return ""
    key, value = step["endCondition"]["conditionTypeKey"], step.get("endConditionValue")
    if key == "time" and value:
        return f"{value / 60:g} min"
    if key == "distance" and value:
        return f"{value:g} m"
    return "按圈键"


def planned_steps(name: str, workout: dict[str, Any]) -> Planned:
    """The plan of one session from the Garmin workout JSON it was pushed as."""
    steps = workout["workoutSegments"][0]["workoutSteps"]
    warmup = cooldown = None
    parts: list[PartPlan] = []
    km = 0.0
    for step in steps:
        if step["type"] == "RepeatGroupDTO":
            inner = step["workoutSteps"]
            work = next(s for s in inner if s["stepType"]["stepTypeKey"] == "interval")
            rest = next((s for s in inner if s["stepType"]["stepTypeKey"] == "recovery"), None)
            pace = _pace_plan(work)
            if pace is None:
                continue
            reps = int(step["numberOfIterations"])
            parts.append({**pace, "reps": reps, "rest": _rest_text(rest)})
            km += reps * pace["dist_m"] / 1000
            if rest is not None and rest["endCondition"]["conditionTypeKey"] == "distance":
                km += (reps - 1) * rest["endConditionValue"] / 1000
            continue
        key = step["stepType"]["stepTypeKey"]
        pace = _pace_plan(step)
        if pace is None:
            continue
        km += pace["dist_m"] / 1000
        if key == "warmup":
            warmup = pace
        elif key == "cooldown":
            cooldown = pace
        elif key == "interval":
            parts.append({**pace, "reps": 1, "rest": ""})
    race = re.search(r"parkrun|race", name, re.IGNORECASE) is not None
    if race:
        kind: Kind = "race"
    elif warmup is None:
        kind = "long" if "Long run" in name else "easy"
    else:
        kind = "quality"
    target = None
    if race and parts:
        target = (parts[0]["slow"] + parts[0]["fast"]) / 2 * parts[0]["dist_m"] / 1000
    return {
        "kind": kind,
        "warmup": warmup,
        "parts": parts,
        "cooldown": cooldown,
        "target_s": target,
        "km": round(km, 2),
    }


# --- per-second samples ----------------------------------------------------------


@dataclass(frozen=True)
class Samples:
    """Per-second samples of one run. Each sample owns the interval since the
    previous one (`dt`, `dd`; 0 across a pause); `t` and `d` are the moving
    time and distance up to and including it."""

    t: list[float]
    d: list[float]
    dt: list[float]
    hr: list[float | None]

    @classmethod
    def from_steps(cls, dt: list[float], dd: list[float], hr: list[float | None]) -> Samples:
        t, d, tt, dist = [], [], 0.0, 0.0
        for a, b in zip(dt, dd, strict=True):
            tt += a
            dist += b
            t.append(tt)
            d.append(dist)
        return cls(t=t, d=d, dt=list(dt), hr=list(hr))

    def __len__(self) -> int:
        return len(self.t)

    def before(self, i: int) -> tuple[float, float]:
        """(metres, seconds) before sample i."""
        return (self.d[i - 1], self.t[i - 1]) if i > 0 else (0.0, 0.0)

    def span(self, a: int, b: int) -> tuple[float, float]:
        """(metres, seconds) of samples a..b inclusive."""
        d0, t0 = self.before(a)
        return self.d[b] - d0, self.t[b] - t0

    def hr_stats(self, a: int, b: int) -> tuple[float | None, float | None]:
        """Time-weighted average and max heart rate of samples a..b."""
        pairs = [(self.hr[i], self.dt[i]) for i in range(a, b + 1) if self.hr[i] is not None]
        if not pairs:
            return None, None
        weight = sum(w for _, w in pairs)
        if weight > 0:
            avg = sum(h * w for h, w in pairs) / weight
        else:
            avg = sum(h for h, _ in pairs) / len(pairs)
        return avg, max(h for h, _ in pairs)

    def smoothed_speed(self) -> list[float]:
        n, k = len(self), SMOOTH_HALF_S
        out = []
        for i in range(n):
            dist, secs = self.span(max(0, i - k), min(n - 1, i + k))
            out.append(dist / secs if secs > 0 else 0.0)
        return out

    def index_at(self, metres: float) -> int:
        """First sample whose cumulative distance reaches `metres`."""
        return min(bisect.bisect_left(self.d, metres), len(self) - 1)


EMPTY = Samples(t=[], d=[], dt=[], hr=[])


def _pace(dist_m: float, time_s: float) -> float | None:
    return time_s / dist_m * 1000 if dist_m > 0 and time_s > 0 else None


# --- quality reps ----------------------------------------------------------------


def _stretches(s: Samples, threshold_mps: float, min_s: float) -> list[tuple[int, int]]:
    speed = s.smoothed_speed()
    raw: list[list[int]] = []
    for i, v in enumerate(speed):
        if v > threshold_mps and s.dt[i] > 0:
            if raw and s.t[i] - s.t[raw[-1][1]] <= MERGE_GAP_S:
                raw[-1][1] = i
            else:
                raw.append([i, i])
    return [(a, b) for a, b in raw if s.span(a, b)[1] >= min_s and s.span(a, b)[0] > 0]


def _fit(dist_m: float, part: PartPlan) -> float:
    return abs(dist_m - part["dist_m"]) / part["dist_m"]


def find_reps(s: Samples, planned: Planned) -> list[Rep]:
    """Work reps: stretches faster than halfway between the E pace and the
    slowest work pace, given to the plan's parts in order. A stretch moves on
    to the next part when the current part has all its reps, or when the next
    part's distance fits it better. Stretches after the last part are extra."""
    parts = planned["parts"]
    if not parts or len(s) == 0:
        return []
    slowest = max(p["slow"] for p in parts)
    easy_fast = planned["warmup"]["fast"] if planned["warmup"] else slowest + 60.0
    threshold_pace = (slowest + max(easy_fast, slowest)) / 2
    shortest = min(p["dist_m"] / 1000 * p["fast"] for p in parts)
    min_s = max(MIN_REP_S, MIN_REP_SHARE * shortest)
    reps: list[Rep] = []
    part, count, prev_end = 0, 0, None
    for a, b in _stretches(s, 1000.0 / threshold_pace, min_s):
        dist, secs = s.span(a, b)
        if part < len(parts) and count > 0:
            nxt = part + 1
            full = count >= parts[part]["reps"]
            better = nxt < len(parts) and _fit(dist, parts[nxt]) < _fit(dist, parts[part])
            if full or better:
                part, count = nxt, 0
        hr_avg, hr_max = s.hr_stats(a, b)
        pace = secs / dist * 1000
        rest = None if prev_end is None else s.before(a)[1] - s.t[prev_end]
        rep: Rep = {
            "part": None,
            "n": 0,
            "dist_m": dist,
            "time_s": secs,
            "pace": pace,
            "hr_avg": hr_avg,
            "hr_max": hr_max,
            "rest_s": rest,
            "verdict": "extra",
            "off_s": 0.0,
            "start_m": s.before(a)[0],
        }
        if part < len(parts):
            p = parts[part]
            count += 1
            rep["part"], rep["n"] = part, count
            if pace < p["fast"] - PACE_TOLERANCE_S:
                rep["verdict"], rep["off_s"] = "fast", p["fast"] - pace
            elif pace > p["slow"] + PACE_TOLERANCE_S:
                rep["verdict"], rep["off_s"] = "slow", pace - p["slow"]
            else:
                rep["verdict"] = "ok"
        reps.append(rep)
        prev_end = b
    return reps


# --- 5 km effort -----------------------------------------------------------------


def fastest_5k(s: Samples) -> Effort | None:
    """The fastest continuous 5 km; the whole run when it is shorter."""
    n = len(s)
    if n == 0 or s.d[-1] <= 0:
        return None
    a, b, full = 0, n - 1, False
    if s.d[-1] >= FIVE_K:
        best, i, full = None, 0, True
        for j in range(n):
            while i < j and s.span(i + 1, j)[0] >= FIVE_K:
                i += 1
            dist, secs = s.span(i, j)
            if dist >= FIVE_K and (best is None or secs < best):
                best, a, b = secs, i, j
    dist, secs = s.span(a, b)
    hr_avg, hr_max = s.hr_stats(a, b)
    base = s.before(a)[0]
    splits: list[Split] = []
    start = a
    for k in range(1, int(dist // 1000) + 1):
        end = min(s.index_at(base + 1000 * k), b)
        splits.append(
            {"km": k, "time_s": s.span(start, end)[1], "hr_avg": s.hr_stats(start, end)[0]}
        )
        start = end + 1
        if start > b:
            break
    return {
        "dist_m": dist,
        "time_s": secs,
        "pace": secs / dist * 1000,
        "hr_avg": hr_avg,
        "hr_max": hr_max,
        "splits": splits,
        "full": full,
        "start_m": base,
    }


# --- one session -----------------------------------------------------------------


def _km(m: float) -> str:
    return f"{m / 1000:.1f} km"


def _warm_cool_note(planned: Planned, warm: float, cool: float) -> Note | None:
    texts = []
    if planned["warmup"] is not None:
        texts.append(f"热身 {_km(warm)}（计划 {_km(planned['warmup']['dist_m'])}）")
    if planned["cooldown"] is not None:
        texts.append(f"放松 {_km(cool)}（计划 {_km(planned['cooldown']['dist_m'])}）")
    if not texts:
        return None
    text = "，".join(texts) + "。时间紧时可以缩短，不算未完成。"
    if planned["warmup"] is not None and warm < SHORT_WARMUP_M:
        text += "热身不到 1 km 时，快段前至少慢跑几分钟再起速。"
    return {"verdict": "neutral", "text": text}


def _quality_notes(planned: Planned, reps: list[Rep]) -> list[Note]:
    want = sum(p["reps"] for p in planned["parts"])
    got = [r for r in reps if r["part"] is not None]
    if not got:
        return [{"verdict": "watch", "text": "没找到明显快于 E 配速的段落，这次可能没做质量部分。"}]
    notes: list[Note] = []
    if len(got) >= want:
        notes.append({"verdict": "good", "text": f"质量部分完成：{len(got)}/{want} 组。"})
    else:
        notes.append({"verdict": "watch", "text": f"质量部分只找到 {len(got)}/{want} 组。"})
    extra = len(reps) - len(got)
    if extra:
        notes.append(
            {"verdict": "neutral", "text": f"另有 {extra} 段计划外的快跑（如加速跑），没算进去。"}
        )
    fast = [i for i, r in enumerate(got, 1) if r["verdict"] == "fast"]
    slow = [i for i, r in enumerate(got, 1) if r["verdict"] == "slow"]
    if not fast and not slow:
        notes.append({"verdict": "good", "text": "每组配速都在计划区间内。"})
    for label, idx, advice in (
        ("快于", fast, "按当前水平控住配速，跑快了恢复成本更高，收益不多。"),
        ("慢于", slow, "下次照旧用这一档配速，不用硬提。"),
    ):
        if idx:
            which = "、".join(f"第 {i} 组（{got[i - 1]['off_s']:.0f} 秒/km）" for i in idx)
            notes.append({"verdict": "watch", "text": f"{which}{label}区间。{advice}"})
    hrs = [r["hr_avg"] for r in got if r["hr_avg"] is not None]
    if len(hrs) >= 2:
        notes.append(
            {
                "verdict": "neutral",
                "text": f"快段平均心率：第 1 组 {hrs[0]:.0f}，最后一组 {hrs[-1]:.0f}。",
            }
        )
    return notes


def _race_notes(planned: Planned, effort: Effort | None, name: str) -> list[Note]:
    if effort is None:
        return [{"verdict": "watch", "text": "没有逐秒记录，算不出 5 km 用时。"}]
    notes: list[Note] = []
    target = planned["target_s"]
    if not effort["full"]:
        notes.append(
            {
                "verdict": "watch",
                "text": f"全程只有 {_km(effort['dist_m'])}，不到 5 km，按实际距离看配速。",
            }
        )
    if target is not None:
        if effort["full"]:
            diff = effort["time_s"] - target
            sign = "+" if diff >= 0 else "−"
            text = (
                f"最快连续 5 km 用时 {mmss(effort['time_s'])}，"
                f"计划 {mmss(target)}（{sign}{mmss(abs(diff))}）。"
            )
            per_km = diff / 5
        else:
            per_km = effort["pace"] - target / 5
            text = f"平均配速 {mmss(effort['pace'])}/km，计划 {mmss(target / 5)}/km。"
        verdict: Verdict
        if "steady" in name:
            verdict = "watch" if per_km < -PACE_BAND else "good"
            if verdict == "watch":
                text += "这次是 steady，按计划配速跑，不用冲。"
        else:
            verdict = "good" if per_km <= PACE_BAND else "neutral"
        notes.append({"verdict": verdict, "text": text})
    splits = effort["splits"]
    if len(splits) >= 2:
        first = splits[0]["time_s"]
        if first < effort["pace"] - FIRST_KM_FAST_S:
            notes.append(
                {
                    "verdict": "watch",
                    "text": f"第 1 km {mmss(first)}，比平均快 {effort['pace'] - first:.0f} 秒，"
                    "起步偏快。",
                }
            )
        else:
            notes.append({"verdict": "good", "text": f"第 1 km {mmss(first)}，起步没有冲太快。"})
    return notes


def _easy_notes(planned: Planned, actual: Actual) -> list[Note]:
    plan_m = planned["parts"][0]["dist_m"] if planned["parts"] else planned["km"] * 1000
    notes: list[Note] = [
        {"verdict": "neutral", "text": f"跑了 {_km(actual['dist_m'])}，计划 {_km(plan_m)}。"}
    ]
    if planned["parts"] and actual["pace"] is not None:
        e = planned["parts"][0]
        rng = f"{mmss(e['fast'])}–{mmss(e['slow'])}"
        if actual["pace"] < e["fast"] - EASY_FAST_S:
            notes.append(
                {
                    "verdict": "watch",
                    "text": f"平均配速 {mmss(actual['pace'])}/km，快于 E 区间（{rng}）。"
                    "E 跑宁慢勿快。",
                }
            )
        else:
            notes.append(
                {
                    "verdict": "good",
                    "text": f"平均配速 {mmss(actual['pace'])}/km，没有快于 E 区间（{rng}）。",
                }
            )
    return notes


def worst(notes: list[Note]) -> Verdict | None:
    """The session's verdict: watch if any note is, else good if any note is;
    neutral notes (warm-up, heart rate) alone do not make it neutral."""
    verdicts = {n["verdict"] for n in notes}
    for v in ("watch", "good", "neutral"):
        if v in verdicts:
            return v  # type: ignore[return-value]
    return None


def _totals_actual(row: dict[str, Any]) -> Actual:
    """A run judged from its activity totals only."""
    dist = float(row.get("distance_m") or 0.0)
    secs = float(row.get("moving_duration_s") or row.get("duration_s") or 0.0)
    return {
        "activity_id": int(row["activity_id"]),
        "start_time_local": row["start_time_local"],
        "activity_type": row["activity_type"],
        "dist_m": dist,
        "time_s": secs,
        "pace": _pace(dist, secs),
        "hr_avg": row.get("avg_hr_bpm"),
        "others": 0,
        "warmup_m": None,
        "cooldown_m": None,
        "reps": [],
        "effort": None,
    }


def review_session(
    planned: Planned, samples: Samples, activity: dict[str, Any], name: str = ""
) -> tuple[Actual, list[Note]]:
    """Judge one run against its planned session. `activity` is the
    `activities` row (id, type, start time, totals); `samples` may be empty."""
    actual = _totals_actual(activity)
    has = len(samples) > 0 and samples.d[-1] > 0
    if has:
        actual["dist_m"], actual["time_s"] = samples.d[-1], samples.t[-1]
        actual["pace"] = _pace(samples.d[-1], samples.t[-1])
        actual["hr_avg"] = samples.hr_stats(0, len(samples) - 1)[0]
    if planned["kind"] in ("easy", "long"):
        return actual, _easy_notes(planned, actual)
    if not has:
        return actual, [{"verdict": "watch", "text": "没有逐秒记录，分不出快段。"}]
    span: tuple[float, float] | None = None  # metres where the work starts and ends
    if planned["kind"] == "quality":
        reps = find_reps(samples, planned)
        actual["reps"] = reps
        notes = _quality_notes(planned, reps)
        work = [r for r in reps if r["part"] is not None]
        if work:
            span = (work[0]["start_m"], work[-1]["start_m"] + work[-1]["dist_m"])
    else:
        effort = fastest_5k(samples)
        actual["effort"] = effort
        notes = _race_notes(planned, effort, name)
        if effort is not None and effort["full"]:
            span = (effort["start_m"], effort["start_m"] + effort["dist_m"])
    if span is not None:
        actual["warmup_m"] = span[0]
        actual["cooldown_m"] = max(0.0, actual["dist_m"] - span[1])
        note = _warm_cool_note(planned, span[0], actual["cooldown_m"])
        if note is not None:
            notes.append(note)
    return actual, notes


# --- the whole plan --------------------------------------------------------------


def _pushed(state: dict[str, Any], root: Path) -> tuple[list[dict[str, Any]], bool, list[str]]:
    """The scheduled sessions with their workout JSON (None when it cannot be
    recovered), whether any steps were rebuilt, and warnings."""
    scheduled = [w for w in state.get("workouts", []) if w.get("schedule_id")]
    if all("workout" in w for w in scheduled):
        return scheduled, False, []
    settings = state.get("settings") or {}
    pushed = state.get("pushed_at_utc") or state["start"]
    try:
        plan = plan_5k(
            today=date.fromisoformat(settings.get("today") or pushed[:10]),
            target_s=settings.get("target_s") or DEFAULT_TARGET_S,
            current_s=settings.get("current_s"),
            root=root,
            days=settings.get("days") or DEFAULT_DAYS,
            parkrun_day=settings.get("parkrun_day", DEFAULT_PARKRUN_DAY),
        )
        rebuilt = {
            (w["date"], w["name"]): w["workout"]
            for w in plan_workouts(plan, date.fromisoformat(state["start"]))
        }
    except ValueError as err:
        return [{**w, "workout": None} for w in scheduled], True, [f"重建计划失败：{err}"]
    out, missing = [], 0
    for w in scheduled:
        workout = w.get("workout") or rebuilt.get((w["date"], w["name"]))
        missing += workout is None
        out.append({**w, "workout": workout})
    warnings = [
        "推送记录里没有每节课的步骤（旧版推送），按推送当天的设置重建了计划。"
        "重新推送一次后会把步骤一起存下来。"
    ]
    if missing:
        warnings.append(f"{missing} 节课和重建的计划对不上，只显示距离，不比配速。")
    return out, True, warnings


def _runs_by_date(root: Path, first: str, last: str) -> dict[str, list[dict[str, Any]]]:
    db = open_analysis_db(root)
    if db is None or last < first:
        return {}
    with db:
        types = sorted(RUNNING_TYPES)
        marks = ",".join("?" * len(types))
        rows = db.query(
            "SELECT activity_id, activity_type, start_time_local, distance_m, duration_s,"
            " moving_duration_s, avg_hr_bpm FROM a.activities"
            f" WHERE activity_type IN ({marks})"
            " AND substr(start_time_local, 1, 10) BETWEEN ? AND ?"
            " ORDER BY start_time_local",
            [*types, first, last],
        ).to_dicts()
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(row["start_time_local"][:10], []).append(row)
    return out


def _samples(root: Path, activity_ids: list[int], run_walk: RunWalk) -> dict[int, Samples]:
    db = open_analysis_db(root) if activity_ids else None
    if db is None:
        return {}
    with db:
        recs = load_records(db, activity_ids)
    if recs.is_empty():
        return {}
    df = classify_records(recs, run_walk)
    out: dict[int, Samples] = {}
    for (aid,), part in df.group_by("activity_id"):
        part = part.sort("ts")
        out[int(aid)] = Samples.from_steps(
            part["dt_s"].to_list(), part["dd_m"].to_list(), part["heart_rate"].to_list()
        )
    return out


METHOD: Method = {
    "name": "计划复盘",
    "description": (
        "计划来自最后一次推送到 Garmin 的 5K 计划（state/plan5k_push.json），"
        "每节课按推送时的步骤比；当天最长的一次跑步算这节课。"
        "质量课：逐秒速度做 11 秒平滑，快于“E 配速和最慢工作配速的中点”的连续段算一组，"
        "相隔不到 8 秒的合并，太短的丢掉；按顺序分给计划里的各段，"
        "每组配速和区间比（容差 1 秒/km）。第一组之前算热身，最后一组之后算放松。"
        "parkrun/比赛：最快的连续 5 km 和计划用时比，看第 1 km 有没有冲太快；"
        "不到 5 km 按全程算。热身和放松只列出来，跑短了不算未完成。"
        "E 跑/长距离：距离和计划比，平均配速只在快于 E 区间时提醒。"
    ),
    "params": {
        "smooth_half_s": SMOOTH_HALF_S,
        "merge_gap_s": MERGE_GAP_S,
        "min_rep_share": MIN_REP_SHARE,
        "min_rep_s": MIN_REP_S,
        "pace_tolerance_s": PACE_TOLERANCE_S,
        "first_km_fast_s": FIRST_KM_FAST_S,
        "easy_fast_s": EASY_FAST_S,
        "pace_band_s": PACE_BAND,
    },
}


def _status(d: str, today: str, ran: bool) -> Status:
    if ran and d <= today:
        return "done"
    if d < today:
        return "missed"
    return "today" if d == today else "upcoming"


def _on_pace(planned: Planned, actual: Actual) -> bool:
    want = sum(p["reps"] for p in planned["parts"])
    got = [r for r in actual["reps"] if r["part"] is not None]
    return len(got) >= want and all(r["verdict"] == "ok" for r in got)


def _totals(sessions: list[SessionReview]) -> Totals:
    past = [s for s in sessions if s["status"] in ("done", "missed")]
    done = [s for s in past if s["status"] == "done" and s["actual"] is not None]
    quality = [s for s in done if s["planned"] and s["planned"]["kind"] == "quality"]
    return {
        "sessions": len(sessions),
        "past": len(past),
        "done": len(done),
        "missed": len(past) - len(done),
        "quality_done": len(quality),
        "quality_on_pace": sum(_on_pace(s["planned"], s["actual"]) for s in quality),
        "planned_km": round(sum(s["planned"]["km"] for s in past if s["planned"]), 1),
        "done_km": round(sum(s["actual"]["dist_m"] for s in done) / 1000, 1),
    }


def plan_review(today: date | None = None, root: Path | None = None) -> PlanReview:
    inputs = section_inputs(today, root)
    today_s = inputs.today.isoformat()
    warnings: list[str] = [inputs.config_error] if inputs.config_error else []
    review: PlanReview = {
        "today": today_s,
        "start": None,
        "pushed_at_utc": None,
        "rebuilt": False,
        "sessions": [],
        "totals": None,
        "warnings": warnings,
        "method": METHOD,
    }
    try:
        state = load_state(inputs.root / "state" / STATE_FILE)
        if state is None or not any(w.get("schedule_id") for w in state.get("workouts", [])):
            warnings.append(
                "还没有推送过 5K 计划。用 running-push-plan --apply 推送后，这里会逐节复盘。"
            )
            return review
        pushed, rebuilt, more = _pushed(state, inputs.root)
        start = date.fromisoformat(state["start"])
    except (OSError, ValueError, KeyError, TypeError) as err:
        warnings.append(f"读不了 state/{STATE_FILE}：{err}")
        return review
    warnings.extend(more)
    review.update(start=state["start"], pushed_at_utc=state.get("pushed_at_utc"), rebuilt=rebuilt)
    pushed.sort(key=lambda w: w["date"])
    dates = {w["date"] for w in pushed}
    runs = _runs_by_date(inputs.root, pushed[0]["date"], min(pushed[-1]["date"], today_s))
    chosen = {
        d: max(rows, key=lambda r: r["distance_m"] or 0.0) for d, rows in runs.items() if d in dates
    }
    planned_by = {
        w["date"]: planned_steps(w["name"], w["workout"]) if w["workout"] else None for w in pushed
    }
    detailed = [
        int(r["activity_id"])
        for d, r in chosen.items()
        if (p := planned_by.get(d)) is not None and p["kind"] in ("quality", "race")
    ]
    samples = _samples(inputs.root, detailed, inputs.config.run_walk)
    sessions: list[SessionReview] = []
    for w in pushed:
        d, planned, row = w["date"], planned_by[w["date"]], chosen.get(w["date"])
        status = _status(d, today_s, row is not None)
        actual, notes = None, []
        if status == "done" and row is not None:
            if planned is None:
                actual = _totals_actual(row)
            else:
                one = samples.get(int(row["activity_id"]), EMPTY)
                actual, notes = review_session(planned, one, row, w["name"])
            actual["others"] = len(runs[d]) - 1
        sessions.append(
            {
                "date": d,
                "week": (date.fromisoformat(d) - start).days // 7 + 1,
                "name": w["name"],
                "status": status,
                "planned": planned,
                "actual": actual,
                "notes": notes,
                "verdict": worst(notes),
            }
        )
    review["sessions"] = sessions
    review["totals"] = _totals(sessions)
    return review
