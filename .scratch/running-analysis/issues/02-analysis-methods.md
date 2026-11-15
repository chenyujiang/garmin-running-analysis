# Survey of methods for aerobic fitness, training load and race prediction

Type: research
Status: resolved
Blocked by: none

## Question

Which established methods exist for each of the three core analyses? What input does each need, and what are its known limits?

- **Aerobic fitness (pace at the same heart rate)**: Efficiency Factor, aerobic decoupling (Pa:HR), pace in a fixed heart-rate zone, GAP (grade-adjusted pace) and so on. How each is computed from the per-second data stream.
- **Training load**: TRIMP (Banister / Edwards / Lucia), CTL/ATL/TSB (the Banister impulse-response model), ACWR. Which physiological parameters they need (maximum heart rate, resting heart rate, lactate threshold heart rate).
- **Race prediction**: the Riegel formula, Daniels VDOT, VO2max-based methods, and what has been published about how Garmin Race Predictor works. Which past results or training data they need.
- For comparison: how Garmin's own Training Load / VO2max / Race Predictor are computed (Firstbeat's published material).

## Answer

The full survey report (with source numbers and how well each point was verified) was handed back to the charting session only as text and has not been written to the `research/analysis-methods` branch yet; see Comments. Summary of conclusions:

- **Aerobic fitness**: the main metric is "GAP pace at the same heart rate": fit `speed~HR` for each steady run, take the predicted GAP speed at a fixed reference heart rate, and take the weekly median. Supporting metrics: EF (GAP speed ÷ heart rate, steady segments only), and aerobic decoupling (steady runs of ≥60 minutes; ≤5% is good). Grade correction starts with Minetti 2002's `Cr(i)` polynomial. All three metrics are affected by temperature and heart-rate drift and need to be stratified by weather.
- **Training load**: per-run load is Banister TRIMP summed second by second (it needs only HRmax, HRrest and sex, so all 5 years can be back-computed). The trend is the EWMA of CTL(42)/ATL(7)/TSB, a relative measure only. The full Banister performance model is not fitted: there are too few races, and the parameters are ill-conditioned (Hellard 2006). ACWR serves only as a "load spike" hint; there is no causal evidence linking it to injury (Impellizzeri 2020).
- **Race prediction**: the main method is Daniels VDOT, with Riegel `T2=T1(D2/D1)^1.06` for comparison; with ≥2 results a personal exponent is fitted. Both underestimate marathon times (Vickers 2016, n=2303), so add a weekly-volume correction and backtest against past marathons.
- **Garmin/Firstbeat approach**: VO2max is based on heart-rate–speed segments and is sensitive to HRmax (a 15 bpm error gives about 7–9% error). Training Load is based on EPOC; the window for chronic load is not published. Race Predictor = VO2max + training history, with unpublished weights.
- **To be provided by the user**: measured HRmax (not 220−age), HRrest (Garmin's daily data is enough), LTHR (Friel's 30-minute test or a past all-out race), a hand-kept list of races (date, distance, time, all-out or not, weather), sex; optionally a reference heart rate.
- **Sources not read in the original**: the TrainingPeaks help centre, the Strava GAP blog post, Riegel's original paper, the books by Daniels and Edwards, the original source of the Banister TRIMP coefficients. Check the relevant formulas again before writing code.

## Comments

- 2026-10-23: the harness blocked the research subagent when it tried to write the report to a file ("Subagents should return findings as text, not write report files"), so the `research/analysis-methods` branch is currently empty. The full report is kept in the charting session's conversation.
- 2026-10-23 correction: the main session later wrote the report to branch `research/analysis-methods` (commit `25730f8`); "the branch is empty" above is out of date.
