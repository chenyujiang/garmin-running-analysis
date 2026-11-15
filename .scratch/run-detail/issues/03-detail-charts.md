# 03: Per-second curves

**What to build:** the detail page shows curves for heart rate, pace, GAP pace, altitude and cadence on a shared time axis, marking pauses, walking and steady-state segments, with a crosshair readout.

**Blocked by:** 02

**Status:** done

Source: User Stories 10–12, and "Per-second series" under Implementation Decisions, in the [implementation spec](../spec.md).

- [x] Server-side downsampling to at most 1500 points: split time into equal buckets, take the mean within each bucket; pauses never span a bucket
- [x] Pauses, walking and steady state are returned as lists of `[start_s, end_s]` intervals; steady state reuses `aerobic.steady_state`
- [x] GAP reuses `aerobic.gap_speed`; without altitude the grade is 0, the same as the long-run table
- [x] Frontend: the curves stacked vertically on a shared time axis; intervals shaded in light colours; the crosshair readout follows the aerobic fitness chart
- [x] Seam 3 tests: point count ≤ 1500; pause intervals do not span buckets; interval start and end seconds; without heart rate the heart-rate series is empty with a reason

## Outcome (implementation notes)

- Code is in the ticket 03 block of `analysis/src/running/detail.py`: `_series(d)`, registered in `SECTIONS` as `"series"`. `GET /api/activities/{id}` gains `series`: `duration_s`, `bucket_s`, `t_s`, `hr_bpm`, `pace_s_per_km`, `gap_pace_s_per_km`, `altitude_m`, `cadence_spm`, `intervals{pause, walking, steady}`, `unavailable`, `method`.
- Time axis: wall-clock seconds since the first sample. Pauses take their real space (not compressed), so the times match Garmin's playback.
- Downsampling: the bucket width is a whole number of seconds; choose the smallest w such that, with each pause-free stretch bucketed by w separately, the total number of buckets is ≤ 1500 (`MAX_POINTS`). Pauses (sample gap > `run_walk.pause_gap_s`, default 10 seconds) cut the records into stretches, and buckets start at the first sample of each stretch, so a bucket never spans a pause. Within a bucket, t, heart rate, speed, GAP speed, altitude and cadence are averaged arithmetically, rounded to 1 decimal.
- Pace = 1000 / mean speed in the bucket; buckets with mean speed below 0.5 m/s (`MIN_PACE_SPEED_MPS`) have null pace, and the frontend breaks the line there instead of plotting tens of minutes per km.
- GAP: uses the `gap_mps` output of `aerobic.steady_state` directly (which calls `gap_speed` internally, with 30-second smoothed speed, 30-second window grade, clamped to ±0.15). Same definition as the long-run table; without altitude the grade is 0 and GAP equals pace.
- Intervals: a sample stands for "the dt_s seconds up to it", so a run of consecutive marked samples is the interval [t of the first sample − dt_s, t of the last sample]. A pause interval = [last sample before the pause, first sample after resuming]; a pause always cuts walking and steady-state segments.
- Walking segments = the seconds the run/walk classifier marks as walking (10-second trailing mean cadence < 140 spm), so boundaries lag the real switch by about 5 seconds. Steady-state segments use the full `steady_state` filter, including the 10-minute warm-up and the 145 ± 15 bpm heart-rate band, the same steady state as the aerobic fitness chart and the long-run table.
- Missing data: without per-second records every series and interval list is `[]`, reason "没有逐秒记录" (no per-second records); without heart rate `hr_bpm` and `steady` are `[]`, reason "没有心率记录" (no heart-rate records); likewise "没有速度记录" (no speed records), "没有海拔记录" (no altitude records), "没有步频记录" (no cadence records). Non-running activities get only heart rate and altitude; pace, GAP, cadence, walking and steady-state segments are `null`, reason "仅跑步类活动" (running activities only).
- `steady_state` is imported locally inside `_series`, so as not to compete with the parallel tickets 04–06 over the import block at the top of the file.
- Frontend in the ticket 03 block of `static/run.js`: `seriesSection`. Four charts stacked vertically: heart rate, pace (y axis reversed, fast on top, with GAP pace as a dashed line on the same chart), altitude, cadence; only the bottom chart has time ticks. The y axis takes the 2%–98% percentiles plus an 8% margin; spikes are clamped to the edge. Pauses, walking and steady state are shaded in light colours, and the legend lists only the intervals present in this activity. The crosshair follows the aerobic fitness chart: one dashed line through all charts, snapping to the nearest bucket, with a readout line listing the time, the interval it falls in, and each value. Missing series are not drawn; a small line under the charts gives the reason. `style.css` is unchanged; shading uses inline SVG fills.
- Tests: `analysis/tests/test_detail_series_api.py`, 7 Seam 3 tests (a two-hour run reduced to 1000–1500 points; an 11-second pause with different heart rate on each side, not mixed by 15-second buckets; start and end seconds of walking and steady-state intervals; no heart rate; cycling; GAP value on a 10% climb, and no altitude; no per-second records). Synthetic data gains `synthetic_aerobic.add_paused_hr_run`, a run with heart rate and a pause.
