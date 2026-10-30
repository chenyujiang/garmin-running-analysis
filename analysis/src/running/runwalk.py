"""Running vs walking, per second, and running pace from running seconds only.

Classification (spec, "跑和走"):

1. cadence × 2 = spm (FIT stores single-foot cadence);
2. trailing time-window mean over `smoothing_s` seconds (nulls ignored);
3. smoothed spm ≥ `cadence_spm` is running;
4. a walking stretch (by the smoothed value) that holds fewer than `min_walk_s`
   seconds of actual walking (unsmoothed spm below the threshold) is turned back
   into running. Measuring the raw seconds matters: the trailing mean stretches
   an 8 s stop at a crossing to about 15 s of "walking".

Each sample owns the interval since the previous sample of the same activity:
`dt_s` = time since the previous sample, `dd_m` = distance gained since it.
Intervals longer than `pause_gap_s` are pauses and count as neither time nor
distance. The first sample of an activity has dt = dd = 0.

Running pace = Σ dd over running samples ÷ Σ dt over running samples.
Activities without any cadence samples (no FIT, or no cadence sensor) fall
back to the activity totals from Garmin, marked `source = "activity"`.
"""

import polars as pl

from running.config import RunWalk
from running.db import AnalysisDb

# Garmin activity type keys that count as running (road, treadmill, trail, ...).
RUNNING_TYPES: frozenset[str] = frozenset(
    {
        "running",
        "street_running",
        "track_running",
        "treadmill_running",
        "indoor_running",
        "trail_running",
        "ultra_run",
        "obstacle_run",
        "virtual_run",
    }
)

_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def classify_records(records: pl.DataFrame, settings: RunWalk) -> pl.DataFrame:
    """Add `spm`, `spm_smooth`, `dt_s`, `dd_m` and `running` (bool) to records.

    `records` needs `activity_id`, `ts` (Datetime), `cadence` and `distance`
    (and optionally `speed`, used when `distance` is missing). Rows come back
    sorted by activity and time."""
    window = f"{settings.smoothing_s}s"
    by = "activity_id"
    df = records.sort(by, "ts").with_columns(
        (pl.col("cadence") * 2).alias("spm"),
        pl.col("ts").diff().dt.total_seconds().over(by).fill_null(0).alias("gap_s"),
    )
    dd_from_distance = pl.col("distance").diff().over(by)
    dd_from_speed = pl.col("speed") * pl.col("gap_s") if "speed" in df.columns else pl.lit(None)
    df = df.with_columns(
        pl.col("spm").rolling_mean_by("ts", window_size=window).over(by).alias("spm_smooth"),
        pl.when(pl.col("gap_s") > settings.pause_gap_s)
        .then(0.0)
        .otherwise(pl.col("gap_s"))
        .cast(pl.Float64)
        .alias("dt_s"),
    )
    df = df.with_columns(
        pl.when(pl.col("gap_s") > settings.pause_gap_s)
        .then(0.0)
        .otherwise(pl.coalesce(dd_from_distance, dd_from_speed, pl.lit(0.0)))
        .clip(lower_bound=0.0)
        .alias("dd_m"),
        (pl.col("spm_smooth") >= settings.cadence_spm).fill_null(False).alias("_smooth_running"),
        (pl.col("spm") < settings.cadence_spm).fill_null(False).alias("_raw_walking"),
    )
    # Stretches of equal smoothed classification. A walking stretch with fewer
    # than `min_walk_s` seconds of actual (unsmoothed) walking becomes running:
    # the trailing mean drags a short stop out past its real length.
    df = df.with_columns(
        (pl.col("_smooth_running") != pl.col("_smooth_running").shift(1))
        .fill_null(True)
        .cum_sum()
        .over(by)
        .alias("_stretch")
    )
    df = df.with_columns(
        pl.col("dt_s").filter(pl.col("_raw_walking")).sum().over(by, "_stretch").alias("_walk_s")
    )
    df = df.with_columns(
        (pl.col("_smooth_running") | (pl.col("_walk_s") < settings.min_walk_s)).alias("running")
    )
    return df.drop("gap_s", "_smooth_running", "_raw_walking", "_stretch", "_walk_s")


def running_summaries(
    db: AnalysisDb, settings: RunWalk, since_local: str | None = None
) -> pl.DataFrame:
    """One row per running-type activity starting at or after `since_local`
    (wall-clock ISO date or datetime; all activities when None).

    Columns: activity_id, activity_type, start_time_local, run_distance_m,
    run_duration_s, run_pace_s_per_km, garmin_distance_m, garmin_duration_s,
    garmin_pace_s_per_km, source ("records" or "activity")."""
    tables = db.tables()
    if "activities" not in tables:
        return empty_run_summaries()
    types = sorted(RUNNING_TYPES)
    placeholders = ", ".join("?" for _ in types)
    where = f"activity_type IN ({placeholders})"
    params: list = list(types)
    if since_local is not None:
        where += " AND start_time_local >= ?"
        params.append(since_local)
    acts = db.query(
        "SELECT activity_id, activity_type, start_time_local,"
        " distance_m AS garmin_distance_m, duration_s AS garmin_duration_s,"
        " avg_speed_mps AS garmin_speed_mps"
        f" FROM a.activities WHERE {where} ORDER BY start_time_local",
        params,
    )
    if acts.is_empty():
        return empty_run_summaries()

    per_activity = _empty_record_totals()
    if "records" in tables:
        ids = acts["activity_id"].to_list()
        id_list = ", ".join("?" for _ in ids)
        recs = db.query(
            "SELECT activity_id, strptime(timestamp, ?) AS ts, cadence, speed, distance"
            f" FROM a.records WHERE activity_id IN ({id_list})",
            [_TS_FORMAT, *ids],
        )
        if not recs.is_empty():
            classified = classify_records(recs, settings)
            per_activity = classified.group_by("activity_id").agg(
                pl.col("cadence").is_not_null().any().alias("has_cadence"),
                pl.col("dd_m").filter(pl.col("running")).sum().alias("rec_distance_m"),
                pl.col("dt_s").filter(pl.col("running")).sum().alias("rec_duration_s"),
            )

    out = acts.join(per_activity, on="activity_id", how="left").with_columns(
        pl.col("has_cadence").fill_null(False)
    )
    out = out.with_columns(
        pl.when(pl.col("has_cadence"))
        .then(pl.lit("records"))
        .otherwise(pl.lit("activity"))
        .alias("source"),
        pl.when(pl.col("has_cadence"))
        .then(pl.col("rec_distance_m"))
        .otherwise(pl.col("garmin_distance_m"))
        .fill_null(0.0)
        .alias("run_distance_m"),
        pl.when(pl.col("has_cadence"))
        .then(pl.col("rec_duration_s"))
        .otherwise(pl.col("garmin_duration_s"))
        .fill_null(0.0)
        .alias("run_duration_s"),
        _pace(pl.col("garmin_speed_mps")).alias("garmin_pace_s_per_km"),
    )
    out = out.with_columns(
        pl.when((pl.col("run_distance_m") > 0) & (pl.col("run_duration_s") > 0))
        .then(pl.col("run_duration_s") / pl.col("run_distance_m") * 1000)
        .otherwise(None)
        .alias("run_pace_s_per_km")
    )
    return out.select(_SUMMARY_SCHEMA.keys()).cast(_SUMMARY_SCHEMA)


def _pace(speed_mps: pl.Expr) -> pl.Expr:
    return pl.when(speed_mps > 0).then(1000 / speed_mps).otherwise(None)


_SUMMARY_SCHEMA = {
    "activity_id": pl.Int64,
    "activity_type": pl.String,
    "start_time_local": pl.String,
    "run_distance_m": pl.Float64,
    "run_duration_s": pl.Float64,
    "run_pace_s_per_km": pl.Float64,
    "garmin_distance_m": pl.Float64,
    "garmin_duration_s": pl.Float64,
    "garmin_pace_s_per_km": pl.Float64,
    "source": pl.String,
}


def empty_run_summaries() -> pl.DataFrame:
    return pl.DataFrame(schema=_SUMMARY_SCHEMA)


def _empty_record_totals() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "activity_id": pl.Int64,
            "has_cadence": pl.Boolean,
            "rec_distance_m": pl.Float64,
            "rec_duration_s": pl.Float64,
        }
    )
