# 02: Home band: training load full width, volume and prediction 50/50

**What to build:** On the home page the training load section takes the whole first row of the band; weekly volume and race prediction share the second row at equal width with a divider between them. The mobile single column stays.

**Blocked by:** 01

**Status:** open

Source: User Stories 3–5, and "Dashboard styles" under Implementation Decisions, in the [implementation spec](../spec.md).

- [ ] `.a-band` is two columns `1fr 1fr`; `.band-load` spans both in row 1 with a bottom rule; `.band-volume` is column 1 and `.band-predict` column 2 of row 2, with the left divider on `.band-predict`
- [ ] Padding is adjusted so the first column of each row lines up with the page edge, and the last column with the right edge
- [ ] The training load chart keeps a readable height at full width (its height does not grow with its width); record the choice (fixed CSS height or a new viewBox ratio in `load.js`) in the outcome notes
- [ ] The crosshair and keyboard readout on the load chart still work at the new width
- [ ] At the 980 px breakpoint the band is one column in the order load, volume, prediction, as today
- [ ] `static/style.css` is rebuilt and `build_css.py --check` passes
- [ ] Browser check at 1600 px and 390 px windows: no overflow, no clipped labels in the three sections
- [ ] `ruff format --check`, `ruff check` and `pytest` pass (including the JS tests run by `tests/test_changes_js.py`)
