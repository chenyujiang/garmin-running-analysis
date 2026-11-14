# 08: Documentation updates and a real-data check (HITL)

**What to build:** Update `PRODUCT.md`, `GLOSSARY.md` and `README.md`. The user opens a few runs on real data to check the detail page and the report, and tunes the report thresholds once if needed.

**Blocked by:** 01–07

**Status:** open

Source: "Documentation" under Implementation Decisions, and Further Notes, in the [implementation spec](../spec.md).

- [x] `PRODUCT.md`: single-run review lives on the detail page; deeper exploration across activities stays in Jupyter
- [x] `GLOSSARY.md`: heart-rate zones, training type, analysis report, pace distribution
- [x] `README.md`: the `[zones]` and `[report]` config sections and the new endpoints
- [ ] User check (the agent reads no real route coordinates and reports only aggregate numbers): one easy run, one interval session, one long run, one treadmill run and one non-running activity; do the training-type and pace-distribution verdicts match how the user felt?
- [x] Where a verdict does not match, record the adjusted threshold and the reason

## Threshold adjustments

- 2026-11-04 `interval_speed_ratio` 0.15 → 0.10. On real data the user saw an interval session classified as mixed. The likely cause: the fast reps were less than 15% faster than the run's median speed, so too few reps counted towards `interval_min_reps`. The median speed already includes the fast reps, so 15% is too strict for intervals with a small fast/slow gap (this run was not checked second by second). `interval_min_s` and `interval_min_reps` are unchanged.
- 2026-11-04 check: after the change to 0.10, the user confirmed on the detail page that the run is classified as intervals; 0.10 stays.
