# Definition of the aerobic fitness metric

Type: grilling
Status: resolved
Blocked by: 02

## Question

Which metric exactly does this project use for "aerobic fitness", and how is it computed?

- Which kind of metric (Efficiency Factor, pace in a fixed heart-rate zone, aerobic decoupling, or a combination).
- Which activities and which segments take part: easy runs only? Steady heart-rate segments? Exclude intervals and races?
- Whether the long-term trend is aggregated by week or by month, and how it is smoothed.

## Answer

Decided point by point with the user on 2026-10-23. The basis for the algorithms is in [Survey of methods for aerobic fitness, training load and race prediction](02-analysis-methods.md); terms are in `GLOSSARY.md`: **aerobic fitness**, **reference heart rate**, **steady-state segment**.

**Main metric**: GAP pace at the reference heart rate.

- For each run, fit a straight line `GAP speed ~ heart rate` on the steady-state segments and take the predicted value at the reference heart rate as that run's aerobic fitness value.
- The reference heart rate is fixed at **145 bpm**, about 85% of an LTHR of 170, and set in the config. It stays the same across the 5 years, otherwise the trend breaks. The age-related decline of HRmax is accepted without correction. After looking at real data, adjust it once if the median easy-run heart rate is clearly off 145.
- Displayed as a pace, e.g. "145 bpm 下 5:30/km" (5:30/km at 145 bpm).

**Supporting metrics**:

- EF (GAP speed ÷ heart rate, steady-state segments only): computed and shown together with the main metric.
- Aerobic decoupling: computed only for steady runs of ≥60 minutes, listed separately, not merged into the main trend.

**Activities that take part**:

- Only outdoor road runs, i.e. the `running` type.
- Treadmill runs (pace comes from the accelerometer, unreliable) and trail runs (the GAP formula does not hold on technical terrain) are excluded.
- Races and interval runs are not excluded as whole activities; the steady-state segment filter handles them.

**Steady-state segment filter** (all thresholds are parameters, to be tuned after looking at real data):

1. Drop the first 10 minutes (warm-up, heart-rate lag).
2. Apply a 30-second rolling smooth to both heart rate and speed.
3. Keep only seconds that meet all of: heart rate within ±15 bpm of the reference heart rate; speed change of no more than 5% within 60 seconds; no pause; difference between heart rate and cadence of at least 5 (the user mainly uses wrist optical heart rate, and this rule excludes cadence lock).
4. Runs with less than 10 minutes of valid time do not count.

**Grade correction**: Minetti 2002's `Cr(i)` formula converts actual speed into GAP speed. Grade is computed from barometric altitude: altitude is smoothed first, then grade is computed over a 30-second distance window and clamped to ±15%.

**Temperature**: no correction in the first version. The trend chart also shows each week's mean temperature, to help interpret it. Temperature comes from the watch in the FIT; body heat makes it read high, but relative highs and lows are visible. Once the size of the seasonal swing is known, decide whether to regress against Open-Meteo historical air temperature; that would mean sending the location to a third party.

**Aggregation**: the median of each week's valid runs; weeks with fewer than 2 valid runs stay empty; plus a 4-week rolling median trend line. The monthly view is just a coarser display, with no separate algorithm.

## Comments

- 2026-10-23 addition (raised by the user: they often walk a stretch after running, which makes Garmin's average pace slower):
  - Each second is classified as "run" or "walk" by cadence: 10-second smoothed cadence ≥ 140 spm is running, below is walking; walking stretches shorter than 10 seconds still count as running. FIT's `cadence` is single-foot cadence and must be multiplied by 2 to get spm. The threshold 140 is a parameter. The same rule applies to walking in the middle of long runs.
  - The steady-state segment filter gains a rule: only running seconds are used.
  - The main pace of each activity becomes the **running pace** (distance of running seconds ÷ time of running seconds); Garmin's average pace is kept as a reference.
