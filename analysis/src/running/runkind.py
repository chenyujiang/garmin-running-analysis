"""The kind of each run in the activity list (issue #66), first match wins:

- `race`: the activity is named in `races.csv` (`races.read_races`).
- `parkrun`: a parkrun-like run, as on the predictions page (`races.parkruns`:
  Saturday, starting in the morning, 5 km of running).
- `quality`, `long`, `easy`, `mixed`: the detail report's training type
  (`report.training_type`), with interval and tempo runs grouped as `quality`.
- None for non-running activities and runs the report cannot classify
  (no records, or no HR zones and not intervals).
"""

from pathlib import Path
from typing import Literal, get_args

import polars as pl

from running import load
from running.aerobic import load_records, steady_state
from running.config import Config
from running.db import AnalysisDb
from running.races import PARKRUN_HOURS, PARKRUN_M, parkruns, read_races
from running.report import TRAINING_KINDS, TrainingType, training_type
from running.runwalk import RUNNING_TYPES

RunKind = Literal["race", "parkrun", "quality", "long", "easy", "mixed"]
RUN_KINDS: tuple[RunKind, ...] = get_args(RunKind)
_BATCH = 50  # runs whose records are read at once

# One sentence block for the activity list's method.
RUN_KIND_NOTE = (
    "分类按先后取第一个符合的：races.csv 里写了 activity_id 的是比赛；"
    f"周六当地 {PARKRUN_HOURS[0]}–{PARKRUN_HOURS[1]} 点开始、"
    f"跑的距离 {PARKRUN_M[0] / 1000:g}–{PARKRUN_M[1] / 1000:g} km 的是 parkrun；"
    "其余用详情页分析报告的训练类型：间歇跑和节奏跑算质量课，另有长距离、轻松跑、混合。"
    "判不了训练类型（没有逐秒记录，或没有心率区间且不是间歇跑）的跑步和非跑步类活动不标分类。"
)

# Training kinds by activity: each run depends only on its own records, so a
# run is classified once and reused until the database file or its WAL
# changes, or the settings do. Kept per database path.
_TRAINING_CACHE: dict[Path, tuple[tuple, dict[int, RunKind | None]]] = {}


def run_kinds(
    db: AnalysisDb, config: Config, root: Path, rows: list[dict]
) -> dict[int, RunKind | None]:
    """The run kind of each row (`activity_id`, `activity_type`,
    `start_time_local`, `duration_s`); None for non-running rows."""
    running = [r for r in rows if r["activity_type"] in RUNNING_TYPES]
    races, _ = read_races(root)  # a missing or broken file names no races
    race_ids = {r["activity_id"] for r in races if r["activity_id"] is not None}
    out: dict[int, RunKind | None] = {r["activity_id"]: None for r in rows}
    rest = [r for r in running if r["activity_id"] not in race_ids]
    out.update({r["activity_id"]: "race" for r in running if r["activity_id"] in race_ids})
    parkrun_ids = _parkrun_ids(db, config, rest)
    out.update({r["activity_id"]: "parkrun" for r in rest if r["activity_id"] in parkrun_ids})
    rest = [r for r in rest if r["activity_id"] not in parkrun_ids]
    out.update(_cached_training(db, config, rest))
    return out


def _parkrun_ids(db: AnalysisDb, config: Config, rows: list[dict]) -> set[int]:
    if not rows:
        return set()
    days = [load.local_day(r) for r in rows]
    return {r["activity_id"] for r in parkruns(db, config.run_walk, min(days), max(days))}


def _cached_training(db: AnalysisDb, config: Config, rows: list[dict]) -> dict[int, RunKind | None]:
    key = (
        db.file_version(),
        config.aerobic,
        config.run_walk,
        config.report,
        config.zones,
        config.physiology,
    )
    path = db.path.resolve()
    cached = _TRAINING_CACHE.get(path)
    known = cached[1] if cached is not None and cached[0] == key else {}
    missing = [r for r in rows if r["activity_id"] not in known]
    if missing:
        known = dict(known)
        for i in range(0, len(missing), _BATCH):
            known.update(_training_kinds(db, config, missing[i : i + _BATCH]))
        _TRAINING_CACHE[path] = (key, known)
    return {r["activity_id"]: known[r["activity_id"]] for r in rows}


def _training_kinds(db: AnalysisDb, config: Config, rows: list[dict]) -> dict[int, RunKind | None]:
    recs = load_records(db, [r["activity_id"] for r in rows])
    frames: dict[int, pl.DataFrame] = {}
    if not recs.is_empty():
        df = steady_state(recs, config.aerobic, config.run_walk)
        frames = {
            k[0]: f.sort("ts") for k, f in df.partition_by("activity_id", as_dict=True).items()
        }
    out: dict[int, RunKind | None] = {}
    for r in rows:
        frame = frames.get(r["activity_id"])
        if frame is None:
            out[r["activity_id"]] = None
            continue
        floors = load.zone_floors_on(config, load.local_day(r))
        t = training_type(frame, floors, r["duration_s"] or 0.0, config.report)
        out[r["activity_id"]] = _from_training(t)
    return out


def _from_training(t: TrainingType) -> RunKind | None:
    """Interval and tempo runs are `quality`; the other types keep their name."""
    if t.kind is None:
        return None
    return "quality" if TRAINING_KINDS[t.kind].quality else t.kind


def all_run_kinds(db: AnalysisDb, config: Config, root: Path) -> dict[int, RunKind | None]:
    """The run kind of every activity in the database. Fills the cache, so
    the dashboard calls it at startup."""
    rows = db.query(
        "SELECT activity_id, activity_type, start_time_local, duration_s FROM a.activities"
    ).to_dicts()
    return run_kinds(db, config, root, rows)
