# 04: Splits: laps and per kilometre

**What to build:** Two tables on the detail page: the watch's lap splits, and per-kilometre splits cut by distance.

**Blocked by:** 02

**Status:** done

Source: User Stories 13–14, and "Per-kilometre splits" and "Lap splits" under Implementation Decisions, in the [implementation spec](../spec.md).

- [x] Laps: read the `laps` table, converting `avg_cadence` ×2 to spm
- [x] Per kilometre: one split for every full 1000 m of `records.distance`; a final split shorter than 1 km is listed separately with its distance
- [x] Each kilometre: running pace (running seconds only), GAP pace, average heart rate, average spm, elevation gain and loss
- [x] Non-running activities have no per-kilometre splits (null with a reason); without laps the lap table is empty with an explanation
- [x] Seam 3 tests: number of splits, distance of the last split, spm conversion, running pace excludes walking when a split contains walking

## Outcome (implementation notes)

- Section `splits`, builder `_splits` in the ticket 04 block of `analysis/src/running/detail.py`, registered in the ticket 04 slot of `SECTIONS`. Returns `laps[]`, `kilometres[] | null`, `unavailable{field: reason}` and `method`.
- `laps[]`: `lap` (from 1, `lap_index + 1`), `distance_m`, `duration_s`, `pace_s_per_km`, `avg_hr_bpm`, `max_hr_bpm`, `avg_cadence_spm`, `elevation_gain_m`, `elevation_loss_m`, ordered by `lap_index`.
  - **Lap duration (our choice)**: `timer_duration_s` (excluding pauses), falling back to `elapsed_duration_s`. Pace uses `avg_speed_mps`, falling back to distance ÷ timer duration.
  - **Laps of non-running activities (our choice)**: laps are still listed, but `pace_s_per_km` and `avg_cadence_spm` are null: cycling cadence is rpm, and ×2 is not spm; same rule as the ticket 02 summary.
  - No laps: `laps` is `[]`, and `unavailable.laps = "手表没有记录圈"` (the watch recorded no laps).
- `kilometres[]`: `km` (from 1), `distance_m`, `partial`, `duration_s`, `running_pace_s_per_km`, `gap_pace_s_per_km`, `avg_hr_bpm`, `avg_cadence_spm`, `elevation_gain_m`, `elevation_loss_m`.
  - Per-second records come from `aerobic.steady_state` (which includes the run/walk classification of `classify_records` and `gap_mps`); formulas are not copied.
  - **Splitting (our choice)**: each sample owns the interval ending at it, and belongs to the kilometre in which that interval starts. Full kilometres report the nominal `distance_m` of 1000; the last split reports `total distance − full kilometres × 1000`, with `partial = true`. Boundaries are off by at most one sample (about 1 second and 0.15 m of elevation at 3 m/s).
  - **Trailing remainder (our choice)**: a remainder shorter than `MIN_LAST_SPLIT_M` (10 m) is not listed, so a split of a few metres does not show a meaningless pace.
  - Running pace = running seconds ÷ running distance; GAP pace = running seconds ÷ Σ(GAP speed × seconds), i.e. the time-weighted mean GAP speed. Average heart rate is weighted by `dt_s` (pauses excluded, reusing the summary's `_weighted_mean`); average cadence covers running seconds only.
  - **Elevation gain and loss (our choice)**: positive and negative sample-to-sample elevation differences are summed separately, without smoothing; barometer noise in real data makes the values slightly high.
  - Non-running activities: `kilometres = null`, `unavailable.kilometres = "仅跑步类活动"` (running activities only). Running activities without per-second distance (treadmill without records): `kilometres = null`, reason "没有逐秒距离记录" (no per-second distance records).
  - `steady_state` is imported locally inside the function, to avoid touching the import lines at the top of the file and keep clear of parallel tickets' edits.
- Frontend: the ticket 04 block of `static/run.js`: `splitsSection`, one "分段" (splits) section, with the "每公里" (per kilometre) table first and then the "手表的圈" (watch laps) table; null shows the reason from `unavailable` or "—". The last split shows its distance after the kilometre number, e.g. "4（0.30 km）". Reuses the global table styles without changing `style.css`; module-level helpers all carry a `split` prefix to avoid name clashes with parallel tickets.
- Tests `analysis/tests/test_detail_splits.py` (Seam 3, 8 tests), with helpers for synthetic laps in the new file `analysis/tests/synthetic_laps.py` (`Lap`, `add_laps`): 3300 m splits into 3 full kilometres plus 300 m; a kilometre containing 200 m of walking has a running pace of about 333.75 s/km (about 467 s for the whole split); GAP pace of 256.1 / 437.0 s/km and 50 m of elevation gain/loss on 5% up- and downhill; lap spm conversion (88 → 176, 84.5 → 169), timer duration and pace; empty with an explanation when there are no laps; a 2 m remainder is not listed; cycling gets null per-kilometre splits with a reason and no lap pace or cadence; a treadmill run without per-second records.
