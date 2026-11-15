# 14: Race prediction and races

**What to build:** The user maintains a list of races by hand in `races.csv`. The third column of the dashboard's first screen shows a prediction table for 5K, 10K, half marathon and marathon: VDOT first, with Riegel and Garmin columns for comparison, and below it the race the prediction is based on. When there has been no race in 6 months, the table fades, red text gives the date of the most recent race, and the user is prompted to update `races.csv`. Below sits a table of recent races, and the aerobic fitness trend chart marks races with dashed lines.

**Blocked by:** 10 (run/walk classification and weekly volume, wired into the dashboard's volume column), 12 (aerobic fitness trend chart)

**Status:** done

Source: User Stories 43–46, 52, 57 and 58, and "Race list" and "Race prediction" under Implementation Decisions, in the [implementation spec](../spec.md).

- [x] Read `races.csv` with fields `date, activity_id, distance_m, time_s, all_out, note`; give a clear message when the file is missing or malformed
- [x] Compute VDOT from the best `all_out` race in the last 6 months, then convert to each distance (check the original source of the VDOT tables before writing code)
- [x] Riegel for comparison: fit a personal exponent when there are 2 or more races, otherwise use 1.06
- [x] Correct the marathon with the last 8 weeks' average weekly volume following Vickers 2016 (check the source of the coefficients first)
- [x] Garmin Race Predictor takes the latest value in `garmin_metrics`; this column stays empty without data
- [x] With no race in 6 months, mark as stale and give no predictions
- [x] The prediction and race endpoints return values, basis, stale flag, and the formula description and parameters
- [x] Formula-level tests: VDOT conversion, Riegel, Vickers correction, values checked against the original sources
- [x] Seam 3 tests: stale when there is no race in 6 months; Riegel uses 1.06 with only 1 race; a message when `races.csv` is missing

## Outcome

- **User decision (overrides "correct VDOT with Vickers for the marathon" above)**: the main prediction for 5K, 10K and half marathon uses VDOT; the main marathon prediction uses Riegel with the Vickers & Vertosick 2016 correction (Model 1 corrects speed, Model 2 corrects the exponent), without applying the coefficients to VDOT. Reason: the paper only has a Riegel-based version. Source: *BMC Sports Sci Med Rehabil* 2016;8:26, PMC5000509, coefficients in Additional file 1 (docx). The checking and test vectors are in `running-tool-notes/formulas.md` §4.
- Weekly volume: the sum of `running_summaries.run_distance_m` over the 56 days up to today ÷ 8, converted to miles (÷ 1.609344) as the paper uses. The paper uses a self-reported "typical weekly volume"; the 8-week average is our definition.
- Vickers inputs use only all-out non-marathon races (distance < 0.95 × marathon): the race with the highest VDOT is the anchor; if another race differs from it in distance by a factor of ≥ 1.5, the highest-VDOT one among those is used with Model 2, otherwise Model 1 is used. Without a non-marathon race in the window, the marathon falls back to VDOT.
- The paper's race difficulty adjustment is not implemented (`races.csv` has no difficulty column); every race counts as normal difficulty.
- Basis race = the all-out race with the highest VDOT within a 6-calendar-month window (boundary day included); races after today do not count.
- Riegel personal exponent: log-log least squares over all all-out races in the window, clamped to [1.01, 1.20]; 1.06 when there are fewer than 2 distinct distances.
- The Garmin column takes the latest row on or before today with non-empty prediction fields; when the `garmin_metrics` table (ticket 06) has not been merged yet it is treated as no data. The Garmin column is still shown when stale.
- Endpoints: `GET /api/predictions` and `GET /api/races`, both supporting `?today=`. Frontend: `predictions.js` in the third column of the first screen, `races.js` in the second column below (non-all-out races greyed out); the aerobic trend chart draws a red dashed line in the week of each race.
- Tests: `tests/test_prediction_formulas.py` (formula level, 25), `tests/test_predictions_api.py` (Seam 3, 15).
