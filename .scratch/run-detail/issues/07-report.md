# 07: Analysis report (fixed rules)

**What to build:** a Chinese analysis report at the top of the detail page: training type, aerobic fitness comparison, heart-rate drift, pacing, load, air temperature. Each item carries its rule name, verdict level, actual values and thresholds; the thresholds are adjustable in `config.toml`.

**Blocked by:** 03, 04, 06

**Status:** done

Source: User Stories 21–30, and "Analysis report" under Implementation Decisions, in the [implementation spec](../spec.md).

- [x] `running/report.py`: pure function `run_report(detail, context)`, each item with `rule, verdict, text, params`; `verdict` is `good`, `neutral`, `watch` or `unknown`
- [x] The six rules implemented per the spec: training type, aerobic fitness comparison, heart-rate drift, pacing, load, air temperature
- [x] New config `[report]`, defaults as in the spec; the temperature threshold reuses `[aerobic].hot_week_c`
- [x] Rules that cannot decide say why (no heart rate, no GPS, too short, not running)
- [x] The report is merged into the response of `GET /api/activities/{activity_id}`
- [x] Frontend: one line per item, verdict first, rule and values expandable; watch in red `#b0281f`
- [x] Seam 3 tests: for each rule, one synthetic activity that hits and one that misses; changing `[report]` thresholds changes the verdict

## Outcome (implementation notes)

- Module `analysis/src/running/report.py`: `report_context(d, detail)` reads the database (per-second steady-state frame, 4-week baseline, the week's TRIMP and TSB); `run_report(detail, context) -> Report` is a pure function. Returns `report: {items[], method{name, description, params}}`; each item has `rule, name, verdict, text, params`. `rule` is an English id (`training_type`, `aerobic`, `drift`, `pacing`, `load`, `heat`), plus a Chinese `name` for the frontend to display (the spec lists only four fields; `name` is our addition).
- The report does not go into `SECTIONS`: it reads the output of other sections (`summary`, `metrics`), so it is computed last in `activity_detail` in `detail.py` and attached as `detail["report"]`.
- Config: `config.py` gains a `Report` dataclass and a `[report]` section, with the 9 defaults from the spec.
- **Training type (our choice of details)**:
  - "30-second smoothed speed" reuses `[aerobic].smoothing_s` (30 s) and the `speed_smooth` computed by `aerobic.steady_state`. The median speed counts only "running" seconds.
  - "Recovery between reps" for intervals: the smoothed speed must drop below the median speed between two fast stretches for them to count as two reps, otherwise they merge into one. A pause (`dt_s = 0`) breaks a rep.
  - Zone shares count only running seconds with heart rate, using raw heart rate; "15 continuous minutes" is judged on smoothed heart rate, so single-second jitter does not break it.
  - Without zones (no heart rate or LTHR) and not intervals, it is unknown with the reason; the interval check does not need heart rate.
  - Training type is neither good nor bad, so its verdict is always neutral.
- **Aerobic fitness comparison (our choice of details)**: baseline = the median of the weekly medians over the `rolling_weeks` (4) weeks before the Monday of this run's week, counting only weeks with ≥ `min_runs_per_week` (2) valid runs. Unlike the trend chart's rolling value, the week right before does not itself need a value. Without a baseline it is unknown; when this run does not count towards aerobic fitness, the reason from ticket 06's `metrics.unavailable.aerobic` is reused.
- **Heart-rate drift**: uses ticket 06's `metrics.ef` directly; 60 minutes and 5% reuse `longruns.MIN_DURATION_S` and `DECOUPLING_LIMIT_PCT` and are not in `[report]`. Under 60 minutes it is neutral, with EF only.
- **Pacing (our choice of details)**: the running seconds are split in half by cumulative distance, and the time-weighted GAP pace of the two halves is compared. Negative split and even pace are both good; a positive split is watch. Interval runs are not judged (unknown).
- **Load (our choice of details)**: reuses `load._activity_trimp` and `load._series`. "TSB before the run" takes the day's point, "TSB next day" takes the next day's point; ATL/CTL uses the day's point, > `load.SPIKE_RATIO` (1.5) is watch, otherwise neutral. The week is Monday to Sunday.
- **Air temperature**: ≥ `hot_week_c` is watch; below it a neutral item is still shown (the spec only covers watch, and no item without data).
- Frontend: `reportSection` in `static/run.js` (the ticket 07 slot, placed before the summary): one `<details>` per item, the summary line being "verdict, rule name, one sentence"; expanding shows the rule id and a `params` table; "怎么算的" (how it is computed) shows `method.description`. CSS is in the ticket 07 block at the end of `style.css`; only watch uses red, unknown uses light grey.
- Tests `analysis/tests/test_detail_report.py` (Seam 3, 31 tests): intervals hit with 3 reps and miss with 2, and 3 reps miss after `interval_min_reps = 4`; tempo hits with 20 continuous minutes and misses when split, and hits after `tempo_min_s = 480`; long, easy, mixed; unknown without heart rate; aerobic fitness better, flat and watch, flat after `aerobic_change = 0.05`, unknown without a baseline and when not counting; drift > 5% watch, 0% good, under 60 minutes neutral; pacing negative split, even, positive split, even after `split_change = 0.04`, intervals not judged; load watch for a first one-hour spike, neutral for the same amount every day; air temperature 25 °C watch, 15 °C neutral, watch after `hot_week_c = 14`, absent without temperature; cycling gets load only.
- 2026-11-04, the user's decision: the aerobic fitness baseline is relaxed to the median of all valid runs in the previous 4 weeks, with no minimum of 2 per week and no weekly medians first; `params.baseline_weeks` becomes `baseline_runs`.
