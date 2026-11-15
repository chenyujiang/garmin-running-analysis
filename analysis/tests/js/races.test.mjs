// Seam: which rows the recent races table shows (static/races.js, no DOM).
// The newest races.csv races are always kept; parkruns fill the rest of the
// 10 rows. The rows stay newest first, as /api/races sends them.

import { test } from "node:test";
import assert from "node:assert/strict";
import { LIMIT, shownRaces } from "../../src/running/dashboard/static/races.js";

const race = (date, source) => ({ date, source });
// Newest first, as the API sends them.
const weekly = (n, source, from = 30) =>
  Array.from({ length: n }, (_, i) => race(`2026-10-${String(from - i).padStart(2, "0")}`, source));

test("the table shows 10 rows", () => {
  assert.equal(LIMIT, 10);
});

test("an older races.csv race is kept when newer parkruns would fill the table", () => {
  const old = race("2026-01-10", "races");
  const rows = shownRaces([...weekly(12, "parkrun"), old]);
  assert.equal(rows.length, 10);
  assert.ok(rows.includes(old));
  assert.equal(rows.filter((r) => r.source === "parkrun").length, 9);
});

test("parkruns fill the rows the races.csv races leave, newest first", () => {
  const races = [race("2026-10-25", "races"), race("2026-02-01", "races")];
  const parkruns = weekly(12, "parkrun", 29);
  const all = [...parkruns, ...races].sort((a, b) => b.date.localeCompare(a.date));
  const rows = shownRaces(all);
  assert.equal(rows.length, 10);
  assert.deepEqual(rows.filter((r) => r.source === "parkrun"), parkruns.slice(0, 8));
  assert.deepEqual(rows.map((r) => r.date), [...rows.map((r) => r.date)].sort().reverse());
});

test("more than 10 races.csv races: only the newest 10, no parkruns", () => {
  const races = weekly(11, "races");
  const rows = shownRaces([...races, race("2026-10-31", "parkrun")].sort((a, b) => b.date.localeCompare(a.date)));
  assert.deepEqual(rows, races.slice(0, 10));
});

test("without races.csv races the newest 10 parkruns are shown", () => {
  const parkruns = weekly(12, "parkrun");
  assert.deepEqual(shownRaces(parkruns), parkruns.slice(0, 10));
});
