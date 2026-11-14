# 10: Run/walk classification and weekly volume in the dashboard volume column

**What to build:** Each run's pace counts only the running seconds, so walking after the run no longer drags the number down. The second column of the dashboard's first screen shows this week's, last week's and the rolling 7-day volume, plus a 12-week bar chart (the unfinished current week's bar is grey), with a "how volume is computed" note next to it.

**Blocked by:** 03 (FIT parsing into `records` and `laps`)

**Status:** done

Source: User Stories 32, 33, 42, 51 and 58, and "Running and walking" and "Weekly volume" under Implementation Decisions, in the [implementation spec](../spec.md).

- [x] Cadence ×2 gives spm, smoothed over 10 seconds; ≥140 spm counts as running; a walk shorter than 10 seconds in a row still counts as running; thresholds come from `config.toml`, with defaults in code
- [x] Running pace = distance over running seconds ÷ duration of running seconds; Garmin's average pace is kept for reference
- [x] Weekly volume counts only running activities (road, treadmill and trail all count) and only the distance of running seconds; it is grouped by calendar week (Monday to Sunday) of `start_time_local`, with a rolling 7-day value as well
- [x] The volume endpoint returns this week, last week, rolling 7 days and a 12-week series, plus a description of the formulas and parameters
- [x] The frontend draws the volume column in hand-written SVG, with prototype variant A's visuals
- [x] Seam 3 tests: with synthetic data covering a run with walking in the middle, an activity spanning two weeks and a treadmill activity, assert the weekly volume and running pace values

## Outcome

- Run/walk classification is in `analysis/src/running/runwalk.py` and weekly volume in `analysis/src/running/volume.py`; endpoint `GET /api/volume` (optional `?today=YYYY-MM-DD` pins the date).
- A stretch classified as walking after smoothing goes back to running only if its raw (unsmoothed) walking seconds are under 10: smoothing stretches an 8-second stop to about 15 seconds, so judging by the smoothed length would miss short stops.
- A sampling gap above 30 seconds (`pause_gap_s`) counts as a watch pause; neither its time nor its distance counts.
- A run without cadence (no FIT, or a FIT with no cadence) falls back to Garmin's total distance and total duration, with `source = "activity"`.
- An activity spanning midnight or a week boundary counts in full on its start day and start week.
- The set of running activity types grows to 9 (including track, indoor, ultra, obstacle and virtual); see `RUNNING_TYPES`.
- Thresholds are in the `[run_walk]` table of `config.toml`: `cadence_spm`, `smoothing_s`, `min_walk_s`, `pause_gap_s`.
- The frontend `static/volume.js` fetches its own data and takes column 2 of the first screen; the load column (09) and the prediction column are added to `band()` in `app.js`.
- Tests: 15 in `analysis/tests/test_volume_api.py`; the synthetic data helper is `analysis/tests/synthetic.py`.
