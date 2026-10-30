"""The hand-kept race list (`races.csv`) and race predictions built on it.

`races.csv` lives in the data directory, UTF-8 (an Excel BOM is fine), with the
columns `date, activity_id, distance_m, time_s, all_out, note`:

- `date` YYYY-MM-DD; `activity_id` optional (the Garmin activity, if any);
- `distance_m` and `time_s` positive numbers (metres, seconds);
- `all_out` yes/no (also true/false, 1/0, y/n, 是/否): only all-out races
  drive predictions;
- `note` free text.

Predictions (5K, 10K, half, marathon):

- Basis: the all-out race with the highest VDOT among those dated within the
  last `WINDOW_MONTHS` (6) calendar months up to today. None = stale: no
  predictions, only the date of the last all-out race.
- VDOT column: Daniels/Gilbert VDOT of the basis, solved back for each distance.
- Riegel column: from the basis; exponent fitted over all all-out races in the
  window when they cover two or more distances, else 1.06.
- Main prediction: VDOT for 5K/10K/half. The marathon uses Vickers & Vertosick
  2016 (Riegel with a mileage-corrected exponent): Model 2 when a second
  non-marathon all-out race in the window has a distance at least 1.5x apart
  from the basis, else Model 1. Weekly mileage is the running distance of the
  last 8 weeks (56 days up to today) / 8, converted km -> miles.
- Garmin column: the latest Race Predictor row in `garmin_metrics` up to today,
  shown even when our own predictions are stale.
"""

import csv
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Literal, TypedDict

import polars as pl

from running.config import Config, data_dir
from running.db import AnalysisDb, open_analysis_db
from running.predict import (
    MARATHON_M,
    RIEGEL_K,
    RIEGEL_K_MAX,
    RIEGEL_K_MIN,
    VICKERS_M1,
    VICKERS_M2,
    VICKERS_RIEGEL_K,
    km_to_miles,
    riegel_exponent,
    riegel_time,
    vdot,
    vdot_time,
    vickers_model1,
    vickers_model2,
)
from running.runwalk import RUNNING_TYPES, running_summaries
from running.section import Method, section_inputs

RACES_FILE = "races.csv"
COLUMNS = ("date", "activity_id", "distance_m", "time_s", "all_out", "note")
WINDOW_MONTHS = 6
VOLUME_WEEKS = 8
VICKERS_MIN_RATIO = 1.5
TRUE = {"yes", "y", "true", "t", "1", "是", "全力"}
FALSE = {"no", "n", "false", "f", "0", "否", ""}
DISTANCES = (
    ("5k", "5K", 5000.0, "race_5k_s"),
    ("10k", "10K", 10000.0, "race_10k_s"),
    ("half", "半马", 21097.5, "race_half_marathon_s"),
    ("marathon", "全马", MARATHON_M, "race_marathon_s"),
)


class Race(TypedDict):
    date: str
    activity_id: int | None
    distance_m: float
    time_s: float
    all_out: bool
    note: str
    pace_s_per_km: float
    vdot: float


class RacesError(TypedDict):
    kind: Literal["missing", "invalid"]
    message: str


class RaceList(TypedDict):
    today: str
    file: str
    races_error: RacesError | None
    races: list[Race]  # up to today, newest first
    method: Method


class Basis(TypedDict):
    date: str
    activity_id: int | None
    distance_m: float
    time_s: float
    vdot: float
    note: str


class PredictionRow(TypedDict):
    key: str
    label: str
    distance_m: float
    predicted_s: float | None
    predicted_method: str | None  # "vdot", "vickers_model1", "vickers_model2"
    vdot_s: float | None
    riegel_s: float | None
    garmin_s: float | None


class GarminBasis(TypedDict):
    date: str


class Predictions(TypedDict):
    today: str
    stale: bool
    races_error: RacesError | None
    basis: Basis | None
    last_race_date: str | None
    window_start: str
    riegel_k: float | None
    riegel_k_source: Literal["personal", "default"] | None
    weekly_km: float
    weekly_miles: float
    vickers_races: list[Basis]
    rows: list[PredictionRow]
    garmin: GarminBasis | None
    method: Method


class _Invalid(Exception):
    pass


def _parse_row(raw: dict) -> Race:
    def number(name: str) -> float:
        text = (raw.get(name) or "").strip()
        try:
            value = float(text)
        except ValueError:
            raise _Invalid(f"{name} 应该是数字，现在是 “{text}”") from None
        if not math.isfinite(value) or value <= 0:
            raise _Invalid(f"{name} 应该大于 0，现在是 “{text}”")
        return value

    text = (raw.get("date") or "").strip()
    try:
        day = date.fromisoformat(text)
    except ValueError:
        raise _Invalid(f"date 应该是 YYYY-MM-DD，现在是 “{text}”") from None
    aid_text = (raw.get("activity_id") or "").strip()
    try:
        aid = int(aid_text) if aid_text else None
    except ValueError:
        raise _Invalid(f"activity_id 应该是整数或留空，现在是 “{aid_text}”") from None
    distance, time_s = number("distance_m"), number("time_s")
    flag = (raw.get("all_out") or "").strip().lower()
    if flag not in TRUE | FALSE:
        raise _Invalid(f"all_out 应该是 yes 或 no，现在是 “{flag}”")
    return {
        "date": day.isoformat(),
        "activity_id": aid,
        "distance_m": distance,
        "time_s": time_s,
        "all_out": flag in TRUE,
        "note": (raw.get("note") or "").strip(),
        "pace_s_per_km": time_s / distance * 1000.0,
        "vdot": vdot(distance, time_s),
    }


def read_races(root: Path | None = None) -> tuple[list[Race], RacesError | None]:
    """All races in `races.csv`, file order. A problem gives no races and an error."""
    path = (root or data_dir()) / RACES_FILE
    if not path.is_file():
        return [], {
            "kind": "missing",
            "message": (
                f"没有找到 {RACES_FILE}（{path}）。请在数据目录里新建它，"
                f"第一行写 {','.join(COLUMNS)}，每场比赛一行。"
            ),
        }
    races: list[Race] = []
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            header = [c.strip() for c in reader.fieldnames or []]
            missing = [c for c in COLUMNS if c not in header]
            if missing:
                raise _Invalid(f"缺少列 {', '.join(missing)}；第一行应该是 {','.join(COLUMNS)}")
            reader.fieldnames = header
            for raw in reader:
                if not any((v or "").strip() for v in raw.values() if isinstance(v, str)):
                    continue
                try:
                    races.append(_parse_row(raw))
                except _Invalid as e:
                    raise _Invalid(f"第 {reader.line_num} 行：{e}") from None
    except _Invalid as e:
        return [], {"kind": "invalid", "message": f"{RACES_FILE} 格式有误：{e}"}
    except (UnicodeDecodeError, csv.Error) as e:
        return [], {"kind": "invalid", "message": f"{RACES_FILE} 读不了：{e}"}
    return races, None


def months_before(d: date, months: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - months, 12)
    m += 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    raise AssertionError("unreachable")


def race_list(today: date | None = None, root: Path | None = None) -> RaceList:
    inputs = section_inputs(today, root)
    today, root = inputs.today, inputs.root
    races, error = read_races(root)
    past = [r for r in races if r["date"] <= today.isoformat()]
    past.sort(key=lambda r: r["date"], reverse=True)
    return {
        "today": today.isoformat(),
        "file": str(root / RACES_FILE),
        "races_error": error,
        "races": past,
        "method": {
            "name": "比赛清单",
            "description": (
                f"读数据目录里手工维护的 {RACES_FILE}，列为 {', '.join(COLUMNS)}。"
                "只列今天及以前的比赛，最新的在前。配速 = time_s ÷ distance_m；"
                "VDOT 按 Daniels & Gilbert（Oxygen Power，1979）的公式算。"
                "只有 all_out 为 yes 的比赛用于成绩预测。"
            ),
            "params": {"file": RACES_FILE, "columns": list(COLUMNS)},
        },
    }


def _weekly_km(db: AnalysisDb | None, config: Config, today: date) -> float:
    if db is None or "activities" not in db.tables():
        return 0.0
    start = today - timedelta(days=VOLUME_WEEKS * 7 - 1)
    runs = running_summaries(db, config.run_walk, since_local=start.isoformat())
    runs = runs.filter(pl.col("start_time_local").str.slice(0, 10) <= today.isoformat())
    return float(runs["run_distance_m"].sum()) / 1000.0 / VOLUME_WEEKS


def _garmin(db: AnalysisDb | None, today: date) -> dict | None:
    if db is None or "garmin_metrics" not in db.tables():
        return None
    cols = [c for *_, c in DISTANCES]
    df = db.query(
        f"SELECT date, {', '.join(cols)} FROM a.garmin_metrics"
        f" WHERE date <= ? AND ({' OR '.join(f'{c} IS NOT NULL' for c in cols)})"
        " ORDER BY date DESC LIMIT 1",
        [today.isoformat()],
    )
    return df.to_dicts()[0] if df.height else None


def _basis(r: Race) -> Basis:
    return {
        "date": r["date"],
        "activity_id": r["activity_id"],
        "distance_m": r["distance_m"],
        "time_s": r["time_s"],
        "vdot": r["vdot"],
        "note": r["note"],
    }


def race_predictions(today: date | None = None, root: Path | None = None) -> Predictions:
    inputs = section_inputs(today, root)
    today, root, config = inputs.today, inputs.root, inputs.config
    races, error = read_races(root)
    window_start = months_before(today, WINDOW_MONTHS)
    all_out = [r for r in races if r["all_out"] and r["date"] <= today.isoformat()]
    recent = [r for r in all_out if r["date"] >= window_start.isoformat()]
    last = max((r["date"] for r in all_out), default=None)
    best = max(recent, key=lambda r: r["vdot"], default=None)

    db = open_analysis_db(root)
    try:
        weekly_km = _weekly_km(db, config, today)
        garmin = _garmin(db, today)
    finally:
        if db is not None:
            db.close()
    miles = km_to_miles(weekly_km)

    k = riegel_exponent([(r["distance_m"], r["time_s"]) for r in recent])
    k_source: Literal["personal", "default"] | None = None
    if best is not None:
        k_source = "default" if k is None else "personal"
        k = RIEGEL_K if k is None else k

    # Vickers inputs: non-marathon all-out races; the basis plus, for Model 2,
    # the best other race at a clearly different distance.
    vickers: list[Race] = []
    short = [r for r in recent if r["distance_m"] < MARATHON_M * 0.95]
    v_base = max(short, key=lambda r: r["vdot"], default=None)
    if v_base is not None:
        vickers = [v_base]
        partners = [
            r
            for r in short
            if max(r["distance_m"], v_base["distance_m"])
            >= VICKERS_MIN_RATIO * min(r["distance_m"], v_base["distance_m"])
        ]
        partner = max(partners, key=lambda r: r["vdot"], default=None)
        if partner is not None:
            vickers.append(partner)

    rows: list[PredictionRow] = []
    for key, label, distance, garmin_col in DISTANCES:
        vdot_s = riegel_s = predicted = None
        how = None
        if best is not None:
            vdot_s = vdot_time(best["vdot"], distance)
            riegel_s = riegel_time(best["time_s"], best["distance_m"], distance, k)
            predicted, how = vdot_s, "vdot"
            if key == "marathon" and len(vickers) == 2:
                a, b = ((r["distance_m"], r["time_s"]) for r in vickers)
                predicted, how = vickers_model2(a, b, miles), "vickers_model2"
            elif key == "marathon" and vickers:
                r = vickers[0]
                predicted, how = (
                    vickers_model1(r["distance_m"], r["time_s"], miles),
                    ("vickers_model1"),
                )
        g = garmin.get(garmin_col) if garmin else None
        rows.append(
            {
                "key": key,
                "label": label,
                "distance_m": distance,
                "predicted_s": predicted,
                "predicted_method": how,
                "vdot_s": vdot_s,
                "riegel_s": riegel_s,
                "garmin_s": float(g) if g is not None else None,
            }
        )

    return {
        "today": today.isoformat(),
        "stale": best is None,
        "races_error": error,
        "basis": _basis(best) if best else None,
        "last_race_date": last,
        "window_start": window_start.isoformat(),
        "riegel_k": k if best is not None else None,
        "riegel_k_source": k_source,
        "weekly_km": weekly_km,
        "weekly_miles": miles,
        "vickers_races": [_basis(r) for r in vickers] if best is not None else [],
        "rows": rows,
        "garmin": {"date": garmin["date"]} if garmin else None,
        "method": _method(config),
    }


def _method(config: Config) -> Method:
    m1, m2 = VICKERS_M1, VICKERS_M2
    return {
        "name": "VDOT 为主，全马用 Vickers 2016，Riegel 和 Garmin 作对照",
        "description": (
            f"依据：最近 {WINDOW_MONTHS} 个月内 all_out 为 yes 的比赛里 VDOT 最高的一场；"
            f"{WINDOW_MONTHS} 个月内没有就标为过期，不给预测值。"
            "VDOT 用 Daniels & Gilbert（Oxygen Power，1979）的公式："
            "VO2 = −4.60 + 0.182258·v + 0.000104·v²（v 单位 m/min），"
            "%max = 0.8 + 0.1894393·e^(−0.012778·t) + 0.2989558·e^(−0.1932605·t)（t 单位 min），"
            "VDOT = VO2 ÷ %max；再对每个距离反解出用时。5K、10K、半马的预测就是 VDOT 的结果。"
            "全马用 Vickers & Vertosick 2016（BMC Sports Sci Med Rehabil 8:26，附件 1）："
            "VDOT 会高估业余跑者的全马，他们按周跑量修正 Riegel。"
            f"有两场距离相差 {VICKERS_MIN_RATIO:g} 倍以上的非全马比赛时用 Model 2："
            "k_r = ln(T₂/T₁) ÷ ln(D₂/D₁)，"
            f"k_全马 = {m2[0]} − {-m2[1]}·k_r − {-m2[2]}·(周英里数 ÷ 10)，"
            "全马 = T₂ × (42195 ÷ D₂)^k_全马；"
            f"只有一场时用 Model 1：先按 Riegel k = {VICKERS_RIEGEL_K} 求速度 v_R（m/s），"
            f"v = {m1[0]} + {m1[1]}·v_R + {m1[2]}·(周英里数 ÷ 10)，全马 = 42195 ÷ v。"
            f"周跑量 = 最近 {VOLUME_WEEKS} 周（含今天的 {VOLUME_WEEKS * 7} 天）跑的秒的距离 ÷ "
            f"{VOLUME_WEEKS}，公里 ÷ 1.609344 换成英里（论文用英里）。"
            "论文的比赛难度调整没有做（races.csv 没有难度列），一律按普通难度。"
            "Riegel 对照：T₂ = T₁ × (D₂/D₁)^k，从依据那场比赛推算；"
            f"窗口内的全力比赛覆盖两个以上距离时，用 ln T 对 ln D 的最小二乘斜率作个人 k，"
            f"截断在 [{RIEGEL_K_MIN}, {RIEGEL_K_MAX}]；否则 k = {RIEGEL_K}。"
            "Garmin 列取 Garmin Race Predictor 今天及以前最近的一次值，没有数据时留空。"
        ),
        "params": {
            "window_months": WINDOW_MONTHS,
            "riegel_k_default": RIEGEL_K,
            "riegel_k_range": [RIEGEL_K_MIN, RIEGEL_K_MAX],
            "volume_weeks": VOLUME_WEEKS,
            "vickers_riegel_k": VICKERS_RIEGEL_K,
            "vickers_model1": list(VICKERS_M1),
            "vickers_model2": list(VICKERS_M2),
            "vickers_min_distance_ratio": VICKERS_MIN_RATIO,
            "vickers_difficulty_adjustment": None,
            "km_per_mile": 1.609344,
            "half_marathon_m": 21097.5,
            "marathon_m": MARATHON_M,
            "volume_activity_types": sorted(RUNNING_TYPES),
            "run_walk_cadence_spm": config.run_walk.cadence_spm,
        },
    }
