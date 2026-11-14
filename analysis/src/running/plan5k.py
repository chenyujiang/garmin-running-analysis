"""An 8-week 5K plan towards a goal time (default sub-20), after Jack Daniels'
VDOT method (Daniels' Running Formula).

What comes from Daniels:
- Training paces from the current VDOT, never from the goal: E, M, T, I, R.
  Intensities as fractions of VO2max, inverted through the Daniels/Gilbert
  VO2-speed curve (`predict._vo2`): E 62-70 %, T 88 %, I 97.5 %; M is the
  VDOT marathon time; R is I minus 6 s per 400 m. These land within a few
  seconds of the VDOT tables (VDOT 50: T 4:15/km, I 3:55/km, R 88 s/400 m).
- Quality caps per session: T at most 10 % of the weekly volume, I at most
  8 % (and 10 km), R at most 5 % (and 8 km). Long run at most 25 % of the week.
- Two quality days a week with easy days between; the training VDOT goes up
  by one only after several weeks at a level (here after week 4, and only when
  the I and T sessions felt controlled).

What is ours: the 8-week layout (3 weeks I-led, a lighter week, 3 weeks of
I + T + R, race week), the volume multipliers and the minimum base.

Run days are the user's (default Tue, Wed, Thu, Sat). With a weekly parkrun
(default Saturday) the near all-out 5K is that week's I session: the plan keeps
one midweek T + R day as far from it as the run days allow, fills the rest
with easy running, and makes week 8's parkrun the goal race. The current
level then also comes from recent parkruns found in the activities.
"""

import math
from datetime import date, timedelta
from pathlib import Path
from typing import Literal, TypedDict

from running.db import open_analysis_db
from running.predict import MARATHON_M, vdot, vdot_time
from running.races import parkruns, race_predictions
from running.section import section_inputs

FIVE_K = 5000.0
DEFAULT_TARGET_S = 20 * 60
WEEKS = 8
MIN_BASE_KM = 30.0
WARMUP_KM = 3.0
COOLDOWN_KM = 2.0
VOLUME = (1.0, 1.0, 1.0, 0.85, 1.1, 1.1, 1.1, 0.7)
CAP = {"T": (0.10, None), "I": (0.08, 10.0), "R": (0.05, 8.0)}
DEFAULT_DAYS = (2, 3, 4, 6)
DEFAULT_PARKRUN_DAY = 6
PARKRUN_WU_KM = 2.0
PARKRUN_CD_KM = 1.5
PARKRUN_WEEKS = 8  # how far back recent parkruns count for the current level

PaceKey = Literal["E", "M", "T", "I", "R"]


class Paces(TypedDict):
    vdot: float
    e_slow: float  # s/km
    e_fast: float
    m: float
    t: float
    i: float
    r: float
    five_k_s: float


class Part(TypedDict):
    reps: int
    dist_m: float
    pace: PaceKey
    rest: str  # recovery between reps as shown, "" for a single rep
    rest_end: Literal["time", "distance"] | None  # how the recovery ends
    rest_value: float | None  # seconds or metres


class Session(TypedDict):
    day: int  # 1 = Monday
    kind: Literal["E", "L", "Q", "rest", "race", "parkrun"]
    km: float
    title: str
    parts: list[Part]
    note: str
    target_s: float | None  # planned 5K time for a parkrun or race


class Week(TypedDict):
    n: int
    phase: str
    vdot: float
    paces: Paces
    km: float
    sessions: list[Session]


class Current(TypedDict):
    source: Literal["races", "parkrun", "override", "assumed"]
    vdot: float
    five_k_s: float
    basis_date: str | None
    basis_distance_m: float | None
    basis_time_s: float | None


class Plan5k(TypedDict):
    today: str
    days: list[int]
    parkrun_day: int | None
    target_s: float
    target_vdot: float
    current: Current
    gap_vdot: float
    feasibility: Literal["close", "stretch", "far"]
    interim_target_s: float | None
    weekly_km_recent: float
    base_km: float
    paces_now: Paces
    paces_goal: Paces
    weeks: list[Week]
    warnings: list[str]
    notes: list[str]  # guidance, not a warning


def _speed_at(vo2: float) -> float:
    """Inverse of `predict._vo2`: m/min where the Daniels/Gilbert VO2 cost is `vo2`."""
    a, b, c = 0.000104, 0.182258, -4.60 - vo2
    return (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a)


def _per_km(fraction: float, value: float) -> float:
    return 60_000.0 / _speed_at(fraction * value)


def training_paces(value: float) -> Paces:
    i = _per_km(0.975, value)
    return {
        "vdot": value,
        "e_slow": _per_km(0.62, value),
        "e_fast": _per_km(0.70, value),
        "m": vdot_time(value, MARATHON_M) / (MARATHON_M / 1000.0),
        "t": _per_km(0.88, value),
        "i": i,
        "r": i - 15.0,  # 6 s per 400 m
        "five_k_s": vdot_time(value, FIVE_K),
    }


def _r1(x: float) -> float:
    return round(x * 2) / 2  # nearest 0.5 km


Rest = tuple[Literal["time", "distance"], float, str]  # (end, seconds or metres, text)


def _jog_min(minutes: float) -> Rest:
    return "time", minutes * 60, f"{minutes:g} 分钟慢跑"


def _jog_m(metres: float) -> Rest:
    return "distance", metres, f"{metres:g} m 慢跑"


_T_REST: Rest = ("time", 60, "1 分钟")
_NO_REST: Rest = ("time", 0, "")

# Planned quality per week: (Q1, Q2), each a list of (reps, dist_m, pace, rest).
_Q = {
    1: ([(5, 1000, "I", _jog_min(3))], [(4, 1600, "T", _T_REST)]),
    2: ([(4, 1200, "I", _jog_min(3))], [(1, 5000, "T", _NO_REST)]),
    3: ([(6, 1000, "I", _jog_min(3))], [(3, 1600, "T", _T_REST), (4, 200, "R", _jog_m(200))]),
    4: ([(8, 400, "R", _jog_m(400))], [(3, 1600, "T", _T_REST)]),
    5: ([(5, 1200, "I", _jog_min(3))], [(4, 1600, "T", _T_REST)]),
    6: ([(6, 1000, "I", _jog_min(2.5))], [(3, 1600, "T", _T_REST), (4, 400, "R", _jog_m(400))]),
    7: ([(5, 1000, "I", _jog_min(2))], [(2, 1600, "T", _T_REST), (6, 200, "R", _jog_m(200))]),
    8: ([(3, 1000, "I", _jog_min(3))], [(4, 200, "R", _jog_m(200))]),
}
_PHASE = {1: "I 期：最大摄氧间歇", 4: "调整周", 5: "专项期：I + T + R", 8: "比赛周"}

# With a weekly parkrun the 5K itself is the VO2max stimulus, so the one
# midweek quality day is T-led with some R for leg speed.
_Q_PARKRUN = {
    1: [(4, 1600, "T", _T_REST)],
    2: [(3, 1600, "T", _T_REST), (4, 200, "R", _jog_m(200))],
    3: [(1, 5000, "T", _NO_REST)],
    4: [(6, 200, "R", _jog_m(200))],
    5: [(4, 1600, "T", _T_REST), (4, 200, "R", _jog_m(200))],
    6: [(3, 1600, "T", _T_REST), (6, 200, "R", _jog_m(200))],
    7: [(2, 1600, "T", _T_REST), (6, 200, "R", _jog_m(200))],
    8: [(2, 1000, "T", _T_REST), (4, 200, "R", _jog_m(200))],
}
_PHASE_PARKRUN = {
    1: "基础：parkrun 全力 + T",
    4: "调整周",
    5: "专项：按新水平跑 parkrun + T + R",
    8: "目标 parkrun",
}


def _capped(parts: list[tuple], week_km: float) -> tuple[list[Part], list[str]]:
    out: list[Part] = []
    notes: list[str] = []
    for reps, dist, pace, rest in parts:
        share, ceiling = CAP[pace]
        limit_km = week_km * share if ceiling is None else min(week_km * share, ceiling)
        if reps > 1:
            fit = max(2, math.floor(limit_km * 1000 / dist))
            if fit < reps:
                notes.append(f"{pace} 量按周跑量上限从 {reps} 组减到 {fit} 组")
                reps = fit
        elif dist / 1000 > limit_km:
            new = max(2000.0, math.floor(limit_km) * 1000.0)
            notes.append(f"连续 T 按周跑量上限从 {dist / 1000:g} km 减到 {new / 1000:g} km")
            dist = new
        end, value, text = rest
        multi = reps > 1
        out.append(
            {
                "reps": reps,
                "dist_m": float(dist),
                "pace": pace,
                "rest": text if multi else "",
                "rest_end": end if multi else None,
                "rest_value": float(value) if multi else None,
            }
        )
    return out, notes


def _quality_km(parts: list[Part]) -> float:
    work = sum(p["reps"] * p["dist_m"] for p in parts) / 1000
    jog = sum((p["reps"] - 1) * 0.4 for p in parts)  # recoveries, about 400 m each
    return WARMUP_KM + work + jog + COOLDOWN_KM


def _title(parts: list[Part]) -> str:
    def one(p: Part) -> str:
        d = f"{p['dist_m'] / 1000:g} km" if p["dist_m"] >= 1000 else f"{p['dist_m']:g} m"
        return f"{d} @{p['pace']}" if p["reps"] == 1 else f"{p['reps']}×{d} @{p['pace']}"

    return " + ".join(one(p) for p in parts)


def _gap(a: int, b: int) -> int:
    """Days between two weekdays, the week wrapping round (Sun to Tue is 2)."""
    d = abs(a - b) % 7
    return min(d, 7 - d)


def _spread(candidates: list[int], hard: list[int], k: int) -> list[int]:
    """Pick `k` days from `candidates`, each as far as possible from the hard
    days already placed (ties go to the earlier day)."""
    picked: list[int] = []
    for _ in range(k):
        free = [d for d in candidates if d not in picked]
        if not free:
            break
        best = max(free, key=lambda d: (min(_gap(d, h) for h in hard + picked), -d))
        picked.append(best)
    return sorted(picked)


def _parkrun(n: int, day: int, paces: Paces, goal_s: float) -> Session:
    km = _r1(PARKRUN_WU_KM + FIVE_K / 1000 + PARKRUN_CD_KM)
    if n == WEEKS:
        return {
            "day": day,
            "kind": "race",
            "km": km,
            "title": "目标 parkrun",
            "parts": [],
            "note": f"均匀配速 {mmss(goal_s / 5)}/km：前 1 km 不快于它，最后 1 km 再加速",
            "target_s": goal_s,
        }
    if n == 4:
        return {
            "day": day,
            "kind": "parkrun",
            "km": km,
            "title": "parkrun 控制跑",
            "parts": [],
            "note": "调整周：按 M 配速跑完，不冲刺",
            "target_s": paces["m"] * 5,
        }
    return {
        "day": day,
        "kind": "parkrun",
        "km": km,
        "title": "parkrun 全力",
        "parts": [],
        "note": (
            f"按训练水平均匀跑，每公里 {mmss(paces['five_k_s'] / 5)}；前 1 km 不要更快，"
            "最后 1 km 有余力再加速。连续两次明显快于这个时间，说明可以提前升一档"
        ),
        "target_s": paces["five_k_s"],
    }


def mmss(s: float) -> str:
    """1200 -> "20:00"."""
    s = round(s)
    return f"{s // 60}:{s % 60:02d}"


def _week(
    n: int,
    base_km: float,
    training_vdot: float,
    days: list[int],
    parkrun_day: int | None,
    goal_s: float,
) -> Week:
    km = _r1(base_km * VOLUME[n - 1])
    paces = training_paces(training_vdot)
    sessions: list[Session] = []
    if parkrun_day is not None:
        # The weekly parkrun is the VO2max stimulus; one T-led quality day
        # sits as far from it as the run days allow.
        anchor = parkrun_day
        sessions.append(_parkrun(n, anchor, paces, goal_s))
        q_days = _spread([d for d in days if d != anchor], [anchor], 1)
        q_raw = [_Q_PARKRUN[n]]
    else:
        anchor = 7 if 7 in days else max(days)
        if n == WEEKS:
            sessions.append(
                {
                    "day": anchor,
                    "kind": "race",
                    "km": _r1(FIVE_K / 1000 + WARMUP_KM + COOLDOWN_KM),
                    "title": "5K 比赛",
                    "parts": [],
                    "note": f"均匀配速 {mmss(goal_s / 5)}/km：前 1 km 不快于它",
                    "target_s": goal_s,
                }
            )
        else:
            sessions.append(
                {
                    "day": anchor,
                    "kind": "L",
                    "km": _r1(min(km * 0.25, 18.0)),
                    "title": "长距离",
                    "parts": [],
                    "note": "全程 E 配速，不超过 150 分钟",
                    "target_s": None,
                }
            )
        q_days = _spread([d for d in days if d != anchor], [anchor], 2)
        q_raw = list(_Q[n])
    for d, raw in zip(q_days, q_raw, strict=False):
        parts, notes = _capped(raw, km)
        sessions.append(
            {
                "day": d,
                "kind": "Q",
                "km": _r1(_quality_km(parts)),
                "title": _title(parts),
                "parts": parts,
                "note": "；".join(notes),
                "target_s": None,
            }
        )
    if n == WEEKS:
        q = [s for s in sessions if s["kind"] == "Q"][-1]
        q["note"] = "比赛周：量减少，跑完应觉得还有余力"

    used = {s["day"] for s in sessions}
    # Farthest from the anchor first: that one is the longer easy run.
    e_days = sorted((d for d in days if d not in used), key=lambda d: (-_gap(d, anchor), d))
    left = max(0.0, km - sum(s["km"] for s in sessions))
    weights = [1.5 if i == 0 and parkrun_day is not None else 1.0 for i in range(len(e_days))]
    for d, wt in zip(e_days, weights, strict=True):
        before = (anchor - d) % 7
        note = ""
        if before in (1, 2):
            note = "可加 4–6 次 20 秒快步（strides）"
        elif (d - anchor) % 7 == 1:
            note = "恢复跑，宁慢勿快"
        sessions.append(
            {
                "day": d,
                "kind": "E",
                # The run days are the user's: keep each, at least 3 km.
                "km": max(3.0, _r1(left * wt / sum(weights))),
                "title": "轻松跑（稍长）" if wt > 1 and len(e_days) > 1 else "轻松跑",
                "parts": [],
                "note": note,
                "target_s": None,
            }
        )
    for d in range(1, 8):
        if all(s["day"] != d for s in sessions):
            sessions.append(
                {
                    "day": d,
                    "kind": "rest",
                    "km": 0.0,
                    "title": "休息或交叉训练",
                    "parts": [],
                    "note": "",
                    "target_s": None,
                }
            )
    sessions.sort(key=lambda s: s["day"])
    table = _PHASE_PARKRUN if parkrun_day is not None else _PHASE
    phase = table.get(n) or table[max(k for k in table if k <= n)]
    return {
        "n": n,
        "phase": phase,
        "vdot": round(training_vdot, 1),
        "paces": paces,
        "km": round(sum(s["km"] for s in sessions), 1),
        "sessions": sessions,
    }


def _parkrun_best(today: date | None, root: Path | None, weekday: int) -> Current | None:
    """Best parkrun-like run (`races.parkruns`) of the last `PARKRUN_WEEKS`."""
    inputs = section_inputs(today, root)
    db = open_analysis_db(inputs.root)
    try:
        start = inputs.today - timedelta(days=PARKRUN_WEEKS * 7 - 1)
        runs = parkruns(db, inputs.config.run_walk, start, inputs.today, weekday)
    finally:
        if db is not None:
            db.close()
    best: Current | None = None
    for r in runs:
        if best is None or r["vdot"] > best["vdot"]:
            best = {
                "source": "parkrun",
                "vdot": r["vdot"],
                "five_k_s": vdot_time(r["vdot"], FIVE_K),
                "basis_date": r["date"],
                "basis_distance_m": r["distance_m"],
                "basis_time_s": r["time_s"],
            }
    return best


def plan_5k(
    today: date | None = None,
    target_s: float = DEFAULT_TARGET_S,
    current_s: float | None = None,
    root: Path | None = None,
    days: list[int] | tuple[int, ...] = DEFAULT_DAYS,
    parkrun_day: int | None = DEFAULT_PARKRUN_DAY,
) -> Plan5k:
    """Raises ValueError for fewer than 3 run days or a parkrun day that is
    not a run day."""
    days = sorted(set(days))
    if len(days) < 3 or any(not 1 <= d <= 7 for d in days):
        raise ValueError("至少选 3 个跑步日")
    if parkrun_day is not None and parkrun_day not in days:
        raise ValueError("parkrun 那天必须是跑步日")
    pred = race_predictions(today=today, root=root)
    target_vdot = vdot(FIVE_K, target_s)
    warnings: list[str] = []
    notes: list[str] = []
    # A parkrun basis is weighed below, on this plan's own parkrun day.
    basis = pred["basis"] if pred["basis_source"] == "races" else None
    parkrun = None if parkrun_day is None else _parkrun_best(today, root, parkrun_day)
    if current_s is not None:
        current: Current = {
            "source": "override",
            "vdot": vdot(FIVE_K, current_s),
            "five_k_s": current_s,
            "basis_date": None,
            "basis_distance_m": None,
            "basis_time_s": None,
        }
    elif parkrun is not None and (basis is None or parkrun["vdot"] > basis["vdot"]):
        current = parkrun
    elif basis is not None:
        current = {
            "source": "races",
            "vdot": basis["vdot"],
            "five_k_s": vdot_time(basis["vdot"], FIVE_K),
            "basis_date": basis["date"],
            "basis_distance_m": basis["distance_m"],
            "basis_time_s": basis["time_s"],
        }
    else:
        assumed = target_vdot - 2.0
        current = {
            "source": "assumed",
            "vdot": assumed,
            "five_k_s": vdot_time(assumed, FIVE_K),
            "basis_date": None,
            "basis_distance_m": None,
            "basis_time_s": None,
        }
        warnings.append(
            "近 6 个月 races.csv 里没有全力比赛，近 8 周也没找到 parkrun，"
            "当前水平按目标 VDOT − 2 假设。"
            "先跑一次 5K 测试，在上方输入成绩，配速才准。"
        )

    gap = target_vdot - current["vdot"]
    feasibility: Literal["close", "stretch", "far"] = (
        "close" if gap <= 1.0 else "stretch" if gap <= 3.0 else "far"
    )
    interim = None
    if feasibility == "far":
        interim = vdot_time(current["vdot"] + 2.0, FIVE_K)
        warnings.append("差距超过 3 个 VDOT。8 周通常只能涨 1–2 个，建议先把中间目标定为下方时间。")

    recent = pred["weekly_km"]
    base_km = max(float(round(recent)), MIN_BASE_KM)
    if recent < MIN_BASE_KM:
        notes.append(
            f"近 8 周平均每周 {recent:.0f} km，计划按 {MIN_BASE_KM:.0f} km 起步。"
            "跑量每 3–4 周最多加一次，每次每周不超过约 10%。"
        )

    vdot_a = current["vdot"]
    vdot_b = min(vdot_a + 1.0, max(target_vdot, vdot_a))
    weeks = [
        _week(n, base_km, vdot_a if n <= 4 else vdot_b, days, parkrun_day, target_s)
        for n in range(1, WEEKS + 1)
    ]
    if any(s["note"] and "上限" in s["note"] for w in weeks for s in w["sessions"]):
        notes.append(
            "按 Daniels 的上限（I ≤ 周量 8%、T ≤ 10%、R ≤ 5%），"
            f"每周 {base_km:.0f} km 时部分质量课的组数被减少。周跑量越高，能做的组数越多。"
        )
    return {
        "today": pred["today"],
        "days": days,
        "parkrun_day": parkrun_day,
        "target_s": target_s,
        "target_vdot": round(target_vdot, 1),
        "current": current,
        "gap_vdot": round(gap, 1),
        "feasibility": feasibility,
        "interim_target_s": interim,
        "weekly_km_recent": round(recent, 1),
        "base_km": base_km,
        "paces_now": training_paces(vdot_a),
        "paces_goal": training_paces(target_vdot),
        "weeks": weeks,
        "warnings": warnings,
        "notes": notes,
    }
