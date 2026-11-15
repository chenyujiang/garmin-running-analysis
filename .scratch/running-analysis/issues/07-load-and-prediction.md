# Training load model and race prediction method

Type: grilling
Status: resolved
Blocked by: 02

## Question

Which method is used for training load, and which for race prediction?

- Load: which TRIMP variant, whether to use CTL/ATL/TSB, and what time constants.
- Where the physiological parameters (maximum heart rate, resting heart rate, lactate threshold heart rate) come from: set by hand, Garmin's values, or estimated from the data; how changes over time are handled.
- Race prediction: Riegel, VDOT, or a method based on the aerobic fitness trend; which past results serve as the basis; which distances to predict.
- Definition of weekly volume: calendar week or rolling 7 days; whether treadmill and trail runs count.

## Comments

- 2026-10-23 (from [Storage design](04-storage.md)): the analysis database holds every activity type, so whether non-running activities (cycling, strength and so on) count towards training load is decided here.
- 2026-10-23 addition (the run/walk rule is in the Comments of [Definition of the aerobic fitness metric](06-aerobic-metric.md)):
  - Weekly volume counts only the distance of running seconds, not the walking parts.
  - TRIMP still counts every second: heart rate stays high while walking, and that is load too.

## Answer

Decided point by point with the user on 2026-10-23. The basis for the algorithms is in [Survey of methods for aerobic fitness, training load and race prediction](02-analysis-methods.md); terms are in `GLOSSARY.md`: **training load**, **race**, **weekly volume**.

**Physiological parameters**:

- The config is a list with effective dates (e.g. `2021-08-01: HRmax 192`). A change affects only calculations after its effective date; historical values use the parameters in effect at the time.
- HRmax: the user has never measured it, so start with the watch setting of 192. As a cross-check, take a high percentile of heart rate from races and all-out runs over the 5 years (after filtering artefacts), and change the config if the gap is large.
- HRrest: fixed at 55 (watch setting), not the daily resting heart rate, because the user does not wear the watch at night and the daily values come from daytime only, which is unreliable.
- LTHR: start with the watch setting of 170.
- Sex: male; the TRIMP coefficients are chosen accordingly.

**Per-session training load**: Banister TRIMP summed second by second, male coefficients `0.64·e^(1.92x)`, `x = (HR − HRrest) / (HRmax − HRrest)`.

- Every activity with heart rate counts, including non-running activities such as cycling and strength training.
- For activities without heart rate, TRIMP is recorded as missing and not estimated; the chart marks "这天有活动但没有负荷数据" (there was an activity this day but no load data).

**Load trend**: CTL is a 42-day EWMA, ATL 7-day, TSB = CTL − ATL, shown only as relative measures; the Banister performance model is not fitted. ATL/CTL > 1.5 is marked "负荷突增" (load spike), as a hint only, not an injury warning.

**Weekly volume**: running only. Counted per calendar week (Monday to Sunday) by `start_time_local`, plus a rolling 7-day value. Road, treadmill and trail runs all count; the treadmill distance error is accepted.

**Race list**: the user maintains `races.csv` by hand in the data directory; it counts as part of the raw archive.

- Fields: `date, activity_id, distance_m, time_s, all_out, note`.
- `activity_id` links to the Garmin activity, so that day's heart rate and temperature can be read.
- Informal all-out runs (such as a 5K time trial) can also be recorded, marked with `all_out`.

**Race prediction** (5K, 10K, half marathon, marathon):

- Main method: take the best all-out race in the last 6 months, compute VDOT, then convert to each distance.
- Comparison: the Riegel formula. With 2 or more races fit a personal exponent, otherwise use 1.06.
- Marathon correction: following Vickers 2016, correct with the average weekly volume of the last 8 weeks, and backtest against past marathon results.
- Reference: also show the Garmin Race Predictor value.
- With no race in 6 months, the prediction shows "过期" (stale) instead of forcing a number.
- Formula details (VDOT tables, Vickers coefficients, original TRIMP coefficients) must be checked against the original sources before writing code; see "sources not read in the original" in the methods survey.
