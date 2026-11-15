# 13: Long-run table: EF and decoupling

**What to build:** A long-run table below the dashboard lists runs of 60 minutes or more with their EF and decoupling, marks decoupling above 5% in red to judge long-run endurance, and has a "how it is computed" note next to it.

**Blocked by:** 11 (aerobic fitness computation and interface)

**Status:** done

Source: User Stories 38, 57 and 58, and "EF and decoupling" under Implementation Decisions, in the [implementation spec](../spec.md).

- [x] EF = GAP speed ÷ heart rate, steady segments only
- [x] Decoupling is computed only for runs of ≥60 minutes and flagged above 5%
- [x] The long-run endpoint returns the recent long runs, each row with date, distance, duration, EF and decoupling, plus a description of the formulas
- [x] The frontend table uses prototype variant A's table style, with decoupling above 5% in red
- [x] Seam 3 tests: a 59-minute run does not appear in the table; the decoupling value and the >5% flag are correct

## Outcome (implementation notes)

- Module `analysis/src/running/longruns.py`: `long_runs(today=None, limit=10, root=None)`; endpoint `GET /api/long-runs?today=YYYY-MM-DD&limit=N` (limit 1–100, default 10).
- Returns `today, has_data, runs[], method{name, description, params}`. `runs[]` goes from newest to oldest start time and holds only runs on or before `today`: `activity_id, activity_type, start_time_local, distance_m, duration_s, steady_s, ef, ef_first, ef_second, decoupling_pct, decoupling_high`.
- Long run = an activity in `RUNNING_TYPES` with `activities.duration_s >= 3600` (treadmill and trail included; without elevation the grade counts as 0).
- Steady segments: reuse `running.aerobic.steady_state`, minus the "heart rate within 145 ± 15" condition (`hr_band_bpm = inf`). Reason: decoupling measures exactly the heart-rate drift, and filtering out the drifted-high seconds by a reference heart rate would hide the drift. The other conditions (warm-up, running, steady speed, first second after a pause, cadence lock) still apply. (Commit 2845fc1 had put the heart-rate band back; on 2026-11-04 the user decided to drop it: `steady_state(..., hr_band=False)`.)
- **EF unit (our own choice)**: m/min ÷ bpm, the time-weighted mean GAP speed ÷ the mean smoothed heart rate. The project is metric throughout; Friel's yards-per-minute figure = this value ÷ 0.9144. GAP uses Minetti rather than NGP, so values cannot be compared with TrainingPeaks directly. Recorded in `method.description` and `method.params.ef_unit`.
- **Decoupling split (our own choice)**: the steady seconds are split in half by cumulative steady time (`method.params.split`), `(EF₁ − EF₂) ÷ EF₁ × 100`. Reason: EF only uses steady segments, and splitting by raw time would put all the warm-up and stops in the first half.
- Fewer than `min_steady_s` (600 s) of steady time, or no heart rate: `ef` and `decoupling_pct` are null and `decoupling_high` is false.
- Frontend `static/longruns.js` (`longRunsSection()`, column 1 of `.a-lower`); `app.js` gains a `lower()` row, with recent races (ticket 15) in column 2. The CSS is in the ticket 13 block at the end of `style.css` (`.a-lower`, `.sec-head`, tables).
- Tests `analysis/tests/test_long_runs_api.py` (Seam 3, 7 tests): 59 minutes does not appear, 60 minutes appears with EF = 1.2; the 5.068% example from formulas.md is marked red; −5% and 4% are not; ordering, limit, today; non-running types excluded; null without heart rate; `has_data=false` without a database. The tests separate the two halves with a 90 s pause so the smoothing window does not span them.
