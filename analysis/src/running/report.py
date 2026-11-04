"""The detail page's analysis report: fixed rules, one item each.

Spec (run-detail), "分析报告". `run_report(detail, context)` is pure: `detail`
is the activity detail (`running.detail.activity_detail` without `report`),
`context` what the rules need beyond it (the per-second frame, the recent
aerobic median, the load around the run day), read once by `report_context`.

Every item is `{rule, name, verdict, text, params}`; `verdict` is `good`,
`neutral`, `watch` or `unknown` (the rule could not judge; `text` says why).
`params` holds the thresholds used and the measured values. Rules, in order:
training type, aerobic value against the recent median, HR drift, pacing,
load, heat. The heat item is left out when there is no air temperature.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Literal, TypedDict

import polars as pl

from running import aerobic, load, longruns
from running.config import Config, ReportThresholds
from running.detail import NO_RECORDS, RUNNING_ONLY
from running.section import Method

if TYPE_CHECKING:
    from running.detail import DetailInputs

Verdict = Literal["good", "neutral", "watch", "unknown"]
LONG_RUN_S = longruns.MIN_DURATION_S  # "long" and the drift verdict start at 60 minutes

TYPE_NAMES = {
    "interval": "间歇跑",
    "tempo": "节奏跑",
    "long": "长距离",
    "easy": "轻松跑",
    "mixed": "混合",
}


class ReportItem(TypedDict):
    rule: str  # stable id
    name: str  # Chinese rule name
    verdict: Verdict
    text: str  # one Chinese sentence
    params: dict  # thresholds and measured values


class Report(TypedDict):
    items: list[ReportItem]
    method: Method


@dataclass(frozen=True)
class AerobicBaseline:
    """Median aerobic value of all valid runs in the weeks before the run's week."""

    speed_mps: float | None
    runs: int  # valid runs that went into the median
    since: str  # first Monday of the window
    until: str  # the run week's Monday (exclusive)


@dataclass(frozen=True)
class LoadAround:
    """Load on and after the run day (`load.load_series`; TSB is the previous day's CTL - ATL)."""

    week_trimp: float  # TRIMP of the run's Monday-to-Sunday week
    week_start: str
    tsb_before: float | None  # TSB on the run day, before its load
    tsb_after: float | None  # TSB on the next day, after the run day's load
    ctl: float | None  # run day, after its load
    atl: float | None


@dataclass(frozen=True)
class ReportContext:
    config: Config
    frame: pl.DataFrame  # `aerobic.steady_state` of the activity's records; may be empty
    baseline: AerobicBaseline | None  # None for non-running activities
    load: LoadAround | None  # None when the activity has no TRIMP


def _item(rule: str, name: str, verdict: Verdict, text: str, params: dict) -> ReportItem:
    return {"rule": rule, "name": name, "verdict": verdict, "text": text, "params": params}


def _pace(speed_mps: float) -> str:
    t = round(1000.0 / speed_mps)
    return f"{t // 60}:{t % 60:02d}/km"


# --- context (reads the database) --------------------------------------------


def report_context(d: DetailInputs, detail: dict) -> ReportContext:
    config = d.config
    recs = aerobic.load_records(d.db, [d.activity_id])
    frame = (
        aerobic.steady_state(recs, config.aerobic, config.run_walk).sort("ts")
        if not recs.is_empty()
        else pl.DataFrame()
    )
    day = date.fromisoformat(d.activity["start_time_local"][:10])
    monday = day - timedelta(days=day.weekday())
    baseline = _baseline(d, monday) if d.is_running else None
    around = _load_around(d, day, monday) if detail["metrics"]["trimp"] is not None else None
    return ReportContext(config=config, frame=frame, baseline=baseline, load=around)


def _baseline(d: DetailInputs, monday: date) -> AerobicBaseline:
    since = monday - timedelta(weeks=d.config.aerobic.rolling_weeks)
    runs = aerobic.aerobic_runs(
        d.db, d.config, since_local=since.isoformat(), until_local=monday.isoformat()
    ).filter(pl.col("valid"))
    speed = float(runs["speed_mps"].median()) if not runs.is_empty() else None
    return AerobicBaseline(speed, runs.height, since.isoformat(), monday.isoformat())


def _load_around(d: DetailInputs, day: date, monday: date) -> LoadAround:
    sunday = monday + timedelta(days=6)
    end = max(sunday, day + timedelta(days=1))
    daily, _, _ = load.daily_trimp(d.db, d.config, end)
    points = {p["date"]: p for p in load.load_series(daily, end)}
    on = points.get(day.isoformat())
    after = points.get((day + timedelta(days=1)).isoformat())
    week = sum(v for k, v in daily.items() if monday <= k <= sunday)
    return LoadAround(
        week_trimp=week,
        week_start=monday.isoformat(),
        tsb_before=on["tsb"] if on else None,
        tsb_after=after["tsb"] if after else None,
        ctl=on["ctl"] if on else None,
        atl=on["atl"] if on else None,
    )


# --- the rules (pure) --------------------------------------------------------


def run_report(detail: dict, context: ReportContext) -> Report:
    training = _training_type(detail, context)
    items = [
        training,
        _aerobic_rule(detail, context),
        _drift(detail),
        _pacing(detail, context, training["params"].get("type")),
        _load_rule(detail, context),
    ]
    heat = _heat(detail, context)
    if heat is not None:
        items.append(heat)
    return {"items": items, "method": _method(context.config)}


def _running_seconds(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty():
        return frame
    return frame.filter(pl.col("running") & (pl.col("dt_s") > 0))


def _stretches(frame: pl.DataFrame, flag: pl.Expr) -> pl.DataFrame:
    """Runs of consecutive samples where `flag` holds (a pause breaks a run):
    columns `_run`, `seconds`, `start`, `end` (row positions in `frame`)."""
    df = frame.with_row_index("_i").with_columns(flag.fill_null(False).alias("_f"))
    pause = pl.col("dt_s") == 0
    key = ((pl.col("_f") != pl.col("_f").shift(1)).fill_null(True) | pause).cum_sum()
    return (
        df.with_columns(key.alias("_run"))
        .filter(pl.col("_f"))
        .group_by("_run")
        .agg(
            pl.col("dt_s").sum().alias("seconds"),
            pl.col("_i").min().alias("start"),
            pl.col("_i").max().alias("end"),
        )
        .sort("start")
    )


def _interval_reps(frame: pl.DataFrame, cfg: ReportThresholds) -> tuple[int, float | None]:
    """Reps: stretches of running seconds whose smoothed speed is at least
    `interval_speed_ratio` above the median and that last `interval_min_s`;
    two such stretches are one rep unless the speed between them drops below
    the median (a recovery). Returns (reps, median speed)."""
    run = _running_seconds(frame)
    speed = run["speed_smooth"].drop_nulls() if not run.is_empty() else pl.Series([])
    if speed.is_empty():
        return 0, None
    median = float(speed.median())
    df = frame.with_columns(
        (pl.col("running") & (pl.col("dt_s") > 0)).alias("_run_s"),
    )
    fast = pl.col("_run_s") & (pl.col("speed_smooth") >= median * (1 + cfg.interval_speed_ratio))
    reps = _stretches(df, fast).filter(pl.col("seconds") >= cfg.interval_min_s)
    speeds = df["speed_smooth"]
    count, prev_end = 0, None
    for start, end in reps.select("start", "end").iter_rows():
        if prev_end is None:
            count = 1
        else:
            between = speeds[prev_end + 1 : start].drop_nulls()
            if not between.is_empty() and float(between.min()) < median:
                count += 1
        prev_end = end
    return count, median


def _zone_shares(detail: dict, frame: pl.DataFrame) -> dict | None:
    """Z1-Z2 and Z3-Z4 shares of the running seconds with HR, and the longest
    unbroken Z3-Z4 stretch (smoothed HR). None without zones."""
    zones = detail["metrics"]["zones"]
    if zones is None or frame.is_empty():
        return None
    floors = [z["low_bpm"] for z in zones["zones"][1:]]  # Z2, Z3, Z4, Z5 floors
    run = _running_seconds(frame).filter(pl.col("heart_rate").is_not_null())
    total = float(run["dt_s"].sum()) if not run.is_empty() else 0.0
    if not total:
        return None
    hr = pl.col("heart_rate")
    easy = float(run.filter(hr < floors[1])["dt_s"].sum())
    tempo = float(run.filter((hr >= floors[1]) & (hr < floors[3]))["dt_s"].sum())
    smooth = pl.col("hr_smooth")
    in_tempo = (
        pl.col("running") & (pl.col("dt_s") > 0) & (smooth >= floors[1]) & (smooth < floors[3])
    )
    stretches = _stretches(frame, in_tempo)
    longest = float(stretches["seconds"].max()) if not stretches.is_empty() else 0.0
    return {
        "running_hr_s": total,
        "z1_z2_share": easy / total,
        "z3_z4_share": tempo / total,
        "longest_z3_z4_s": longest,
    }


def _training_type(detail: dict, ctx: ReportContext) -> ReportItem:
    rule, name = "training_type", "训练类型"
    cfg = ctx.config.report
    if not detail["activity"]["is_running"]:
        return _item(rule, name, "unknown", f"不判训练类型：{RUNNING_ONLY}。", {})
    if ctx.frame.is_empty():
        return _item(rule, name, "unknown", f"不判训练类型：{NO_RECORDS}。", {})
    reps, median = _interval_reps(ctx.frame, cfg)
    duration = detail["summary"]["duration_s"] or 0.0
    params: dict = {
        "interval_reps": reps,
        "median_speed_mps": median,
        "interval_speed_ratio": cfg.interval_speed_ratio,
        "interval_min_s": cfg.interval_min_s,
        "interval_min_reps": cfg.interval_min_reps,
        "duration_s": duration,
    }

    def done(kind: str, why: str) -> ReportItem:
        return _item(
            rule, name, "neutral", f"{TYPE_NAMES[kind]}：{why}。", {"type": kind, **params}
        )

    if reps >= cfg.interval_min_reps:
        return done(
            "interval",
            f"{reps} 段比中位速度快 {cfg.interval_speed_ratio:.0%} 以上、"
            f"持续 {cfg.interval_min_s} 秒以上的快跑，段间有恢复",
        )
    shares = _zone_shares(detail, ctx.frame)
    if shares is None:
        why = detail["metrics"]["unavailable"].get("zones", load.NO_HR)
        return _item(rule, name, "unknown", f"不判训练类型：{why}，也不是间歇跑。", params)
    params.update(
        shares,
        # The shares are of running seconds with HR (`running_hr_s`).
        zone_share_basis="running_hr_s",
        tempo_share=cfg.tempo_share,
        tempo_min_s=cfg.tempo_min_s,
        long_easy_share=cfg.long_easy_share,
        long_min_s=LONG_RUN_S,
        easy_share=cfg.easy_share,
    )
    easy, tempo = shares["z1_z2_share"], shares["z3_z4_share"]
    if tempo >= cfg.tempo_share and shares["longest_z3_z4_s"] >= cfg.tempo_min_s:
        return done(
            "tempo",
            f"Z3–Z4 占跑的时间 {tempo:.0%}，最长连续 {shares['longest_z3_z4_s'] / 60:.0f} 分钟",
        )
    if duration >= LONG_RUN_S and easy >= cfg.long_easy_share:
        return done("long", f"{duration / 60:.0f} 分钟，Z1–Z2 占跑的时间 {easy:.0%}")
    if easy >= cfg.easy_share:
        return done("easy", f"Z1–Z2 占跑的时间 {easy:.0%}")
    return done("mixed", f"Z1–Z2 占跑的时间 {easy:.0%}，Z3–Z4 占 {tempo:.0%}，不属于以上任何一类")


def _aerobic_rule(detail: dict, ctx: ReportContext) -> ReportItem:
    rule, name = "aerobic", "有氧能力对比"
    metrics = detail["metrics"]
    value = metrics["aerobic"]
    change = ctx.config.report.aerobic_change
    if value is None:
        why = metrics["unavailable"].get("aerobic", RUNNING_ONLY)
        return _item(rule, name, "unknown", f"本次不计入有氧能力：{why}。", {})
    base = ctx.baseline
    params: dict = {
        "speed_mps": value["speed_mps"],
        "reference_hr": value["reference_hr"],
        "aerobic_change": change,
        "baseline_since": base.since if base else None,
        "baseline_until": base.until if base else None,
        "baseline_runs": base.runs if base else 0,
        "baseline_speed_mps": base.speed_mps if base else None,
    }
    if base is None or base.speed_mps is None:
        return _item(
            rule,
            name,
            "unknown",
            f"本周之前 {ctx.config.aerobic.rolling_weeks} 周没有计入有氧能力的跑步，无从比较。",
            params,
        )
    ratio = value["speed_mps"] / base.speed_mps - 1
    params["change"] = ratio
    now, then = _pace(value["speed_mps"]), _pace(base.speed_mps)
    hr = value["reference_hr"]
    if ratio >= change:
        verdict, word = "good", f"比之前 4 周的中位数 {then} 快 {ratio:.1%}"
    elif ratio <= -change:
        verdict, word = "watch", f"比之前 4 周的中位数 {then} 慢 {-ratio:.1%}"
    else:
        verdict, word = "neutral", f"和之前 4 周的中位数 {then} 持平（差 {ratio:+.1%}）"
    return _item(rule, name, verdict, f"{hr} bpm 下的 GAP 配速 {now}，{word}。", params)


def _drift(detail: dict) -> ReportItem:
    rule, name = "drift", "心率漂移"
    metrics = detail["metrics"]
    ef = metrics["ef"]
    limit = longruns.DECOUPLING_LIMIT_PCT
    if ef is None:
        why = metrics["unavailable"].get("ef", RUNNING_ONLY)
        return _item(rule, name, "unknown", f"不判心率漂移：{why}。", {})
    params = {
        "ef": ef["ef"],
        "decoupling_pct": ef["decoupling_pct"],
        "decoupling_limit_pct": limit,
        "min_duration_s": LONG_RUN_S,
        "duration_s": detail["summary"]["duration_s"],
    }
    dec = ef["decoupling_pct"]
    if dec is None:
        return _item(
            rule,
            name,
            "neutral",
            f"EF {ef['ef']:.2f}；不足 {LONG_RUN_S // 60} 分钟，不判漂移。",
            params,
        )
    if dec > limit:
        text = f"心率漂移 {dec:.1f}%，超过 {limit:g}%：后半程同样配速心率更高，这个强度难以持续。"
        return _item(rule, name, "watch", text, params)
    text = f"心率漂移 {dec:.1f}%，不超过 {limit:g}%：配速和心率稳定。"
    return _item(rule, name, "good", text, params)


def _pacing(detail: dict, ctx: ReportContext, training: str | None) -> ReportItem:
    rule, name = "pacing", "配速分布"
    change = ctx.config.report.split_change
    if not detail["activity"]["is_running"]:
        return _item(rule, name, "unknown", f"不判配速分布：{RUNNING_ONLY}。", {})
    if training == "interval":
        return _item(rule, name, "unknown", "间歇跑不判配速分布。", {"type": training})
    run = _running_seconds(ctx.frame)
    if run.is_empty() or run["gap_mps"].drop_nulls().is_empty():
        return _item(rule, name, "unknown", "不判配速分布：没有逐秒速度记录。", {})
    run = run.filter(pl.col("gap_mps").is_not_null()).with_columns(
        pl.col("dd_m").cum_sum().alias("_cum")
    )
    total_m = float(run["dd_m"].sum())
    first = run.filter(pl.col("_cum") <= total_m / 2)
    second = run.filter(pl.col("_cum") > total_m / 2)

    def gap_pace(part: pl.DataFrame) -> float | None:
        gap_m = float((part["gap_mps"] * part["dt_s"]).sum())
        return 1000.0 * float(part["dt_s"].sum()) / gap_m if gap_m > 0 else None

    p1, p2 = gap_pace(first), gap_pace(second)
    if p1 is None or p2 is None:
        return _item(rule, name, "unknown", "不判配速分布：跑的距离太短，分不出前后两半。", {})
    faster = (p1 - p2) / p1  # > 0: the second half is faster
    params = {
        "first_gap_pace_s_per_km": p1,
        "second_gap_pace_s_per_km": p2,
        "change": faster,
        "split_change": change,
    }

    def fmt(p: float) -> str:
        return _pace(1000.0 / p)

    halves = f"前半 GAP {fmt(p1)}，后半 {fmt(p2)}"
    if faster >= change:
        return _item(
            rule,
            name,
            "good",
            f"负分割：{halves}，后半快 {faster:.1%}。",
            {"split": "negative", **params},
        )
    if faster <= -change:
        return _item(
            rule,
            name,
            "watch",
            f"正分割：{halves}，后半慢 {-faster:.1%}。",
            {"split": "positive", **params},
        )
    return _item(
        rule,
        name,
        "good",
        f"匀速：{halves}，前后差 {abs(faster):.1%}。",
        {"split": "even", **params},
    )


def _load_rule(detail: dict, ctx: ReportContext) -> ReportItem:
    rule, name = "load", "负荷"
    metrics = detail["metrics"]
    trimp = metrics["trimp"]
    if trimp is None or ctx.load is None:
        why = metrics["unavailable"].get("trimp", load.NO_HR)
        return _item(rule, name, "unknown", f"算不出负荷：{why}。", {})
    ld = ctx.load
    share = trimp / ld.week_trimp if ld.week_trimp > 0 else None
    ratio = ld.atl / ld.ctl if ld.ctl else None
    params = {
        "trimp": trimp,
        "week_start": ld.week_start,
        "week_trimp": ld.week_trimp,
        "week_share": share,
        "tsb_before": ld.tsb_before,
        "tsb_after": ld.tsb_after,
        "ctl": ld.ctl,
        "atl": ld.atl,
        "atl_ctl_ratio": ratio,
        "spike_ratio": load.SPIKE_RATIO,
    }
    parts = [f"TRIMP {trimp:.0f}"]
    if share is not None:
        parts.append(f"占本周 {share:.0%}")
    if ld.tsb_before is not None and ld.tsb_after is not None:
        parts.append(f"TSB 跑前 {ld.tsb_before:+.1f}，第二天 {ld.tsb_after:+.1f}")
    text = "，".join(parts)
    if ratio is not None and ratio > load.SPIKE_RATIO:
        text += f"。当天 ATL/CTL = {ratio:.2f}，超过 {load.SPIKE_RATIO:g}：负荷突增。"
        return _item(rule, name, "watch", text, params)
    return _item(rule, name, "neutral", text + "。", params)


def _heat(detail: dict, ctx: ReportContext) -> ReportItem | None:
    temp = detail["summary"]["air_temperature_c"]
    if temp is None:
        return None
    hot = ctx.config.aerobic.hot_week_c
    params = {"air_temperature_c": temp, "hot_c": hot}
    if temp >= hot:
        text = f"气温 {temp:.1f} °C，不低于 {hot:g} °C：心率可能因热偏高。"
        return _item("heat", "气温", "watch", text, params)
    return _item("heat", "气温", "neutral", f"气温 {temp:.1f} °C，低于 {hot:g} °C。", params)


def _method(config: Config) -> Method:
    r, a = config.report, config.aerobic
    return {
        "name": "分析报告",
        "description": (
            "固定规则，不用模型生成；每条给出规则、阈值和实际数值。"
            "训练类型按顺序判，命中即止：间歇（"
            f"{a.smoothing_s} 秒平滑速度比本次跑的秒的中位速度快 ≥ {r.interval_speed_ratio:.0%}、"
            f"持续 ≥ {r.interval_min_s} 秒的段 ≥ {r.interval_min_reps} 段，"
            "两段之间速度跌到中位速度以下才算分开的两段）；"
            f"节奏跑（Z3–Z4 占跑的时间 ≥ {r.tempo_share:.0%}，"
            f"且平滑心率连续在 Z3–Z4 ≥ {r.tempo_min_s // 60} 分钟）；"
            f"长距离（≥ {LONG_RUN_S // 60} 分钟且 Z1–Z2 ≥ {r.long_easy_share:.0%}）；"
            f"轻松跑（Z1–Z2 ≥ {r.easy_share:.0%}）；其余为混合。区间占比只算跑的、有心率的秒。"
            "有氧能力对比：本次有氧能力值和本周之前 "
            f"{a.rolling_weeks} 周所有计入有氧能力的跑步的中位数比较"
            "（不要求每周的次数），"
            f"快 ≥ {r.aerobic_change:.0%} 为好，慢 ≥ {r.aerobic_change:.0%} 需留意。"
            f"心率漂移：≥ {LONG_RUN_S // 60} 分钟的跑看 decoupling，"
            f"> {longruns.DECOUPLING_LIMIT_PCT:g}% 需留意；更短的只给 EF。"
            "配速分布：跑的秒按距离对半分，比较前后两半的 GAP 配速，"
            f"后半快 ≥ {r.split_change:.0%} 为负分割，"
            f"慢 ≥ {r.split_change:.0%} 为正分割（需留意），"
            "其间为匀速；间歇跑不判。"
            "负荷：本次 TRIMP、占本周（周一到周日）TRIMP 的比例、跑前（当天）和第二天的 TSB；"
            f"当天 ATL/CTL > {load.SPIKE_RATIO:g} 提示负荷突增。"
            f"气温：平均气温 ≥ {a.hot_week_c:g} °C 时提示心率可能因热偏高；没有气温数据时不列。"
        ),
        "params": {
            "interval_speed_ratio": r.interval_speed_ratio,
            "interval_min_s": r.interval_min_s,
            "interval_min_reps": r.interval_min_reps,
            "tempo_share": r.tempo_share,
            "tempo_min_s": r.tempo_min_s,
            "long_easy_share": r.long_easy_share,
            "easy_share": r.easy_share,
            "aerobic_change": r.aerobic_change,
            "split_change": r.split_change,
            "hot_c": a.hot_week_c,
            "smoothing_s": a.smoothing_s,
            "long_run_s": LONG_RUN_S,
            "decoupling_limit_pct": longruns.DECOUPLING_LIMIT_PCT,
            "spike_ratio": load.SPIKE_RATIO,
        },
    }
