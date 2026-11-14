# Storage design

Type: grilling
Status: resolved
Blocked by: 01, 03

## Question

What form should the pulled data be stored in?

- Whether the raw FIT / JSON are kept as they are (as a replayable source of truth).
- Which storage to use for analysis: SQLite, DuckDB, Parquet files, or a combination.
- How the per-second data stream, the summaries and the health data are each organised.
- The storage format must be writable by the Rust import CLI and readable by the Python analysis: how well each side's libraries support it, and which side defines the schema.
- The raw FIT bytes and the raw API JSON are written to disk as they are first, then parsed (see [How the Rust import CLI calls the Garmin APIs](10-rust-api-coverage.md)). The parsed results can be rebuilt from the raw files at any time.

## Answer

Decided point by point with the user on 2026-10-23. The data volume is small (about 1000–1500 activities, about 150–250 MB of raw files, about 2.7 million rows of per-second data), so the choice turns on concurrent access and ease of use, not performance.

**Two layers** (terms in `GLOSSARY.md`): the **raw archive** is the source of truth; the **analysis database** can be deleted at any time and rebuilt from the raw archive.

**The data directory** lives outside the repository, e.g. `%USERPROFILE%\running-data\`, with the path set by config or an environment variable. That way it cannot be committed by mistake, and there is not a separate copy in every worktree.

**Raw archive** (`raw/`):

```
raw/
  personal_api/activities/<activityId>.fit        # extracted from the zip, zip discarded (the zip holds only the FIT and a modification time)
  personal_api/activities/<activityId>.json       # get_activity details
  personal_api/daily_summaries/<YYYY-MM-DD>.json  # one file per day
  garminconnect/<metric>/<YYYY-MM-DD>.json        # daily snapshots of Training Status / VO2max / Race Predictor
  export/<export date>/                           # account data export unpacked as is, archived only, not parsed
```

- Every activity type is pulled and stored, not just running; filtering by type happens at analysis time. That way, if non-running activities are later counted in the load, no new backfill is needed.
- When Garmin later corrects a day's data, re-pulling overwrites that day's file; no history of versions is kept.
- Empty HRV and sleep responses stay only in the raw archive; no tables are created for them (the user does not wear the watch at night).
- Only the raw archive is backed up, not the analysis database.

**Analysis database**: SQLite with WAL mode.

- Writing: Rust with `rusqlite` (bundled feature).
- Reading: Python with `sqlite3`, polars, or DuckDB's sqlite extension querying directly. When columnar analysis is needed, DuckDB reads this SQLite file.
- A DuckDB file was not chosen as the analysis database: only one process can write at a time, which would conflict with syncing while Jupyter or the dashboard is open; and the Rust crate compiles slowly on Windows.
- Parquet was not chosen: heavy dependencies on the Rust side; updating a summary table means rewriting the whole file.
- Rust defines the schema: migration SQL lives in the Rust project and runs automatically when the import CLI starts. Python only reads the analysis database.
- Units are always FIT's SI units (m, m/s, s, bpm); pace is converted only for display in Python.
- Time: `records.timestamp` is stored in UTC. `activities` stores both `start_time_utc` and `start_time_local` (from `startTimeLocal`); weekly volume is counted by local date.

**Tables**:

- `records`: a long table of the per-second data stream, one row per second. Primary key `(activity_id, timestamp)`; fixed columns include `heart_rate`, `speed`, `cadence`, `altitude`, `distance`, `lat`, `lon`, `power` and `temperature`, with NULL for missing values. Private messages (`unknown_*`) are not stored; parse the raw FIT when needed.
- `laps`: the watch's splits.
- `activities`: one row per activity. Typed columns are picked from the detail JSON (type, start time, distance, duration, average/max heart rate, ascent and so on); the full JSON stays only in the raw archive.
- `daily_wellness`: one row per day (resting heart rate and so on), upserted on re-pull.
- `garmin_metrics`: one row per day, holding snapshots of Garmin's three metrics as a reference.

**Derived values** (TRIMP, EF, CTL and so on) are computed in Python on every use for now and not stored. If caching is needed later, it goes into a separate `analysis.sqlite` owned by Python, without touching Rust's analysis database.

**Left to other tickets**: the import CLI needs a "rebuild the analysis database from the raw archive" command; the sync strategy decides when it is triggered.
