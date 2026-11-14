# 11: Aerobic fitness computation and endpoint

**What to build:** Every outdoor road run gets an aerobic fitness value (GAP pace at the reference heart rate), summarised by week into a trend. The dashboard can fetch the weekly series filtered by range through an endpoint. The chart comes in the next ticket.

**Blocked by:** 10 (run/walk classification and weekly volume, wired into the dashboard's volume column)

**Status:** done

Source: User Stories 34–37 and 56, and "Aerobic fitness" under Implementation Decisions, in the [implementation spec](../spec.md).

- [x] Only outdoor road runs count; treadmill and trail runs are excluded
- [x] Steady-state segment: drop the first 10 minutes; apply a 30-second rolling smooth to heart rate and speed; keep only seconds that meet all of: running, heart rate within ±15 bpm of the reference heart rate, speed change ≤5% within 60 seconds, no pause, difference between heart rate and spm ≥5. Each threshold is read from `config.toml`, with defaults in code
- [x] Runs whose steady-state segments total less than 10 minutes do not count
- [x] Grade from smoothed barometric altitude over a 30-second distance window, clamped to ±15%; Minetti 2002's `Cr(i)` converts speed to GAP speed
- [x] Fit a straight line `GAP speed ~ heart rate` on steady-state seconds and take its value at the reference heart rate (default 145)
- [x] Take the weekly median of valid runs; weeks with fewer than 2 stay empty, no interpolation; then a 4-week rolling median; each week's mean temperature comes from the watch temperature in the FIT and is for display only
- [x] The aerobic fitness endpoint takes a range parameter (half year, 1 year, 2 years, all) and returns the weekly series (including empty weeks and temperatures), plus the formula description and parameters
- [x] Formula-level tests: Minetti `Cr(i)` values checked against the original paper
- [x] Seam 3 tests: a week with only 1 valid run returns null; treadmill and trail runs do not count; runs with less than 10 minutes of steady state do not count
- [ ] If the first full backfill is done, check whether the reference heart rate of 145 is close to the median easy-run heart rate in real data; adjust it once if it is clearly off, and record the conclusion (**deferred**: ticket 08's full backfill has not been done, and there is no `running.sqlite` in the data directory yet. After the backfill, check in a notebook with `mean_hr` of `aerobic_runs` or the average heart rate of easy runs)

## Outcome

**Implementation**: `analysis/src/running/aerobic.py`, endpoint `GET /api/aerobic?range=6m|1y|2y|all&today=YYYY-MM-DD` (default `1y`, other values return 422). Tests: `tests/test_minetti.py` (formula level), `tests/test_aerobic_api.py` (Seam 3), synthetic data helper `tests/synthetic_aerobic.py` (`tests/synthetic_hr.py` belongs to ticket 09).

**Definitions we chose** (written into "how it is computed"):

- "Outdoor road run" = Garmin types `running` and `street_running`. `track_running` does not count.
- The thresholds live in the `[aerobic]` section of `config.toml`; field names are in `running.config.Aerobic`. `reference_hr` stays in `[aerobic]`; `Config.reference_hr` is kept and equals `Config.aerobic.reference_hr`.
- The first 10 minutes are dropped by **moving time** (pauses not counted); each sample represents the second before it, and that second must start after the 10 minutes.
- "No pause": the first sample after resuming from a pause (gap > `pause_gap_s`, `dt_s = 0`) is not steady state.
- The heart-rate–spm difference uses the **raw** per-second values, `|HR − spm| ≥ 5`; the heart-rate band uses the smoothed heart rate.
- Stable speed: `(max − min) / mean ≤ 5%` of smoothed speed over the last 60 seconds, a backward-looking window.
- Grade: after a 30-second rolling mean of altitude, the altitude difference between the current point and the point 30 seconds earlier ÷ the distance difference; 0 when the distance difference is < 1 m or altitude is missing.
- Fit: ordinary least squares, not weighted by duration. When the heart-rate variance is < 1 bpm² the line is unreliable, and the mean GAP speed of the steady-state seconds is used instead.
- The 4-week rolling median is the median of the **weekly medians of non-empty weeks** among the last 4 weeks; when the current week is empty the rolling value is empty too (the line breaks at empty weeks). The window reads 3 extra weeks before the start of the range.
- Temperature: each outdoor road run (valid or not) is averaged first, then averaged per week. Treadmill temperatures do not count.
- The endpoint's `runs` lists valid runs only; `weeks[].runs` is the number of valid runs in that week.
- Downhill uses Minetti's full conversion (section 5 of formulas.md notes that at −10% GAP is only 0.6 times the actual speed). Whether a separate downhill cap is needed will be decided once there is real data.
