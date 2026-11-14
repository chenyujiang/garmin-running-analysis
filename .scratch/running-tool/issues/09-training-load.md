# 09: Training load: TRIMP and CTL/ATL/TSB, wired into the dashboard's load column

**What to build:** When the user opens the dashboard, the first column of the first screen shows whether this week's load is normal: a load headline (when ATL/CTL > 1.5 the title turns red and reads "负荷突增：ATL 是 CTL 的 1.6 倍" (load spike: ATL is 1.6 times CTL), with one line of advice below), three big numbers for CTL/ATL/TSB, the CTL/ATL curves of the last 12 weeks with TSB bars, and "负荷怎么算的" (how load is computed) beside them.

**Blocked by:** 03 (FIT parsing into `records` and `laps`)

**Status:** done

Source: User Stories 7, 39–41, 49, 50 and 58, and "Training load" under Implementation Decisions, in the [implementation spec](../spec.md).

- [x] Physiological parameters (HRmax, HRrest, LTHR) are taken by effective date from `config.toml`; each activity uses the set in effect at the time
- [x] Compute Banister TRIMP second by second with the male coefficients `0.64·e^(1.92x)`, `x = (HR − HRrest) / (HRmax − HRrest)`; every activity with heart rate counts, activities without heart rate are recorded as missing and not estimated
- [x] CTL is a 42-day EWMA, ATL 7-day, TSB = CTL − ATL; ATL/CTL > 1.5 is flagged as a "负荷突增" (load spike)
- [x] The load endpoint returns the current values, the series of the last 12 weeks, the spike flag, and the formula name and current parameters needed for "how it is computed"
- [x] The frontend draws the load column in hand-written SVG, styled after prototype variant A, with at most 2 editorial annotations per chart
- [x] Formula-level tests: TRIMP values checked against the original source (check the source of the Banister coefficients before writing code)
- [x] Seam 3 tests: CTL/ATL/TSB values on synthetic data, the spike flag, activities without heart rate recorded as missing

## Outcome

- **Code location**: computation in `analysis/src/running/load.py` (`training_load(today, root)`), endpoint `GET /api/load?today=YYYY-MM-DD` (today when omitted; `?today=` on the page URL is passed through). Frontend in `static/load.js`; the shared hand-written SVG parts are in `static/svg.js`.
- **Recursion uses the 1/N form**: `CTL_t = CTL_{t−1} + (TRIMP_t − CTL_{t−1})/42`, ATL likewise with N=7.
  - Reason: the TrainingPeaks help page's description, WKO and the prototype all use this form, so the numbers match what the user sees in TrainingPeaks.
  - GoldenCheetah's `exp(−1/N)` form differs by only 0.7% after 42 days, which does not matter for relative comparison.
  - The recursion starts on the first activity day with initial value 0. The choice is written into the endpoint's `method.recursion` and `recursion_formula`, and "how it is computed" shows it directly.
- **TSB = yesterday's CTL − yesterday's ATL**, i.e. TrainingPeaks' Form, meaning the state before going out today.
- **ATL/CTL > 1.5 counts as a spike** (requires CTL > 0). `spike_since` is the start date of the current continuous spike, used for the advice under the title and the annotation on the chart.
- **Per-second TRIMP**: Δt is the gap to the next record, capped at `[load] max_sample_gap_s`, default 10 seconds (pauses do not count); the last record counts as 1 second. x is clamped to [0, 1], which the original does not specify. Only the male coefficients 0.64/1.92 are used.
- **Summary heart-rate fallback** (added after code review): activities without heart-rate records but with average heart rate and duration in the summary are estimated with the average-heart-rate form `duration_min · x · 0.64 · e^(1.92x)` and counted in the load; they are returned in `summary_hr_count` and `summary_hr_recent`, and the UI notes them.
- **Missing**: activities with neither heart-rate records nor a summary average heart rate are recorded as missing, reason "没有心率" (no heart rate). Activities on a day with no physiological parameters in effect are also missing, reason "该日期没有生效的生理参数" (no physiological parameters in effect on this date). Neither counts towards the load; both are returned in `missing_hr_count` and `missing_hr_recent`.
- **All activity types count**, summed per day by the date of `start_time_local`.
- **Endpoint fields**: `today`, `has_data`, `current{date,ctl,atl,tsb,ratio}`, `spike`, `spike_since`, `series[{date,trimp,ctl,atl,tsb}]` (last 84 days), `missing_hr_count`, `missing_hr_recent`, `summary_hr_count`, `summary_hr_recent`, `config_error`, `method{name,description,params}`. Activities after `today` do not count; the `today` field echoes the date actually used (consistent with the other endpoints).
- **Test vectors** come from section 1 of the shared notes `formulas.md` (the corrected values from sport-activities-features PR #231: 32.05 and 261.92). The expected CTL/ATL values are closed-form results computed independently by hand with the 1/N recursion.
- **Unverified**: the original source of the Banister coefficients was not read (Morton 1990 and Banister 1991 both returned 403 or exist only as books); only peer-reviewed secondary citations, all consistent.
- **Side finding, not part of this ticket**: when stdout is not UTF-8, `main()` of `running-dashboard` fails on `print` with `UnicodeEncodeError: 'charmap' codec can't encode characters`. Handled in the code review fixes (`main()` switches stdout to UTF-8).
