# 02: Home band: training load full width, volume and prediction 50/50

**What to build:** On the home page the training load section takes the whole first row of the band; weekly volume and race prediction share the second row at equal width with a divider between them. The mobile single column stays.

**Blocked by:** 01

**Status:** done

Source: User Stories 3–5, and "Dashboard styles" under Implementation Decisions, in the [implementation spec](../spec.md).

- [x] `.a-band` is two columns `1fr 1fr`; `.band-load` spans both in row 1 with a bottom rule; `.band-volume` is column 1 and `.band-predict` column 2 of row 2, with the left divider on `.band-predict`
- [x] Padding is adjusted so the first column of each row lines up with the page edge, and the last column with the right edge
- [x] The training load chart keeps a readable height at full width (its height does not grow with its width); record the choice (fixed CSS height or a new viewBox ratio in `load.js`) in the outcome notes
- [x] The crosshair and keyboard readout on the load chart still work at the new width
- [x] At the 980 px breakpoint the band is one column in the order load, volume, prediction, as today
- [x] `static/style.css` is rebuilt and `build_css.py --check` passes
- [ ] Browser check at 1600 px and 390 px windows: no overflow, no clipped labels in the three sections
- [x] `ruff format --check`, `ruff check` and `pytest` pass (including the JS tests run by `tests/test_changes_js.py`)

## Outcome (implementation notes)

- `.a-band` is `grid-cols-[1fr_1fr]`. `.band-load` is `col-[1/-1] row-1` with `px-0`, a bottom rule (`border-b-rule`) and `mb-5` before row 2. `.band-volume` is `col-1 row-2` with `pl-0 pr-7`; `.band-predict` is `col-2 row-2` and keeps its left divider with `pl-7 pr-0`. The old `section + section` and `first-child`/`last-child` padding rules are gone, since each section now sets its own.
- At 980 px the band stays one column in DOM order (load, volume, prediction). The load section drops its bottom rule and margin there, as before.
- Load chart height: a new viewBox ratio in `load.js`, not a fixed CSS height (with `preserveAspectRatio:"none"` a fixed height would stretch the 12 px SVG labels). `LOAD_CHART = { width: 1216, height: 190, tsbHeight: 78 }`: 1216 is the 1280 px page minus 2 x 32 px padding, so at full width the charts are 190 and 78 px tall with labels near 12 px. Below the 980 px breakpoint `loadChartSize(true)` keeps the old 560-wide viewBox, so on a phone the chart and labels stay as today. The choice is read with `matchMedia` when the chart renders; resizing across the breakpoint applies after a reload. The same approach as the aerobic chart (`W = 1256`).
- Tests: `analysis/tests/js/load.test.mjs` covers the wide and narrow chart sizes.
- Crosshair: the load chart itself has no crosshair. The crosshair and readout in the band are on the weekly volume chart (`volume.js`) and map the pointer through `box.width`, so they work at any width; the aerobic crosshair is outside the band and unchanged.
- For the browser check: the weekly volume chart (`W = 380, H = 190` viewBox) now gets about 580 px of width instead of about 310 px, so it renders about 290 px tall with larger labels. It is left as it is (out of this ticket); if it looks too big, a follow-up can widen its viewBox the same way.
