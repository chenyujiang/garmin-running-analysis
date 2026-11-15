// Seam: the run-kind labels in static/runs.js (no DOM needed). The order is
// the API's (`method.params.run_kinds`), the labels the glossary's.

import { test } from "node:test";
import assert from "node:assert/strict";
import { KIND_NAMES } from "../../src/running/dashboard/static/runs.js";

test("KIND_NAMES lists the run kinds in the API's order with their labels", () => {
  assert.deepEqual(Object.entries(KIND_NAMES), [
    ["race", "比赛"],
    ["parkrun", "parkrun"],
    ["quality", "质量课"],
    ["long", "长距离"],
    ["easy", "轻松"],
    ["mixed", "混合"],
  ]);
});
