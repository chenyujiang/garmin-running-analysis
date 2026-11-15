// Seam: the training load chart geometry in static/load.js (no DOM needed).
// The chart spans the home band's full width (1280 px page minus 2 x 32 px
// padding = 1216 px). Its SVG keeps its aspect ratio, so the viewBox must be
// about that wide for the chart to stay about 190 px tall instead of growing
// with the width, and for its 12 px labels to render near 12 px.

import { test } from "node:test";
import assert from "node:assert/strict";
import { LOAD_CHART, loadChartSize } from "../../src/running/dashboard/static/load.js";

test("the load chart viewBox matches the full band width at a readable height", () => {
  assert.equal(LOAD_CHART.width, 1216);
  assert.equal(LOAD_CHART.height, 190);
  assert.equal(LOAD_CHART.tsbHeight, 78);
});

test("below the 980 px breakpoint the load chart keeps its old 560-wide viewBox", () => {
  assert.deepEqual(loadChartSize(true), { width: 560, height: 190, tsbHeight: 78 });
  assert.deepEqual(loadChartSize(false), LOAD_CHART);
});
