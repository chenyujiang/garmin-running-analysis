// Seam: the Web Mercator maths in static/routemap.js (no DOM needed).

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  fitZoom, metresPerPx, scaleLength, tilesFor, worldPx, TILE,
} from "../../src/running/dashboard/static/routemap.js";

test("worldPx puts (0, 0) in the middle of the world and is linear in longitude", () => {
  assert.deepEqual(worldPx(0, 0, 0), [128, 128]);
  const [x] = worldPx(0, 90, 1);
  assert.equal(x, 384);
  const [, yNorth] = worldPx(60, 0, 1);
  assert.ok(yNorth < 256); // north is up
});

test("fitZoom picks the largest zoom at which the box fits", () => {
  // About 2 km east-west at latitude 45.
  const lats = [45, 45.009];
  const lons = [10, 10.0254];
  const z = fitZoom(lats, lons, 900, 420, 32);
  const span = (zz) => worldPx(45, 10.0254, zz)[0] - worldPx(45, 10, zz)[0];
  assert.ok(span(z) <= 900 - 64);
  assert.ok(span(z + 1) > 900 - 64 || worldPx(45, 10, z + 1)[1] - worldPx(45.009, 10, z + 1)[1] > 420 - 64);
});

test("tilesFor covers the view and wraps columns round the antimeridian", () => {
  const ts = tilesFor(-100, 10, 500, 300, 1);
  // Columns -1, 0, 1 by rows 0, 1.
  assert.equal(ts.length, 6);
  assert.deepEqual([...new Set(ts.map((t) => t.x))].sort(), [0, 1]);
  const first = ts.find((t) => t.col === -1 && t.y === 0);
  assert.equal(first.x, 1);
  assert.equal(first.left, -TILE + 100);
  assert.equal(first.top, -10);
});

test("tilesFor skips rows beyond the poles", () => {
  assert.ok(tilesFor(0, -300, 256, 256, 0).every((t) => t.y === 0));
});

test("metresPerPx halves per zoom level and shrinks towards the poles", () => {
  assert.ok(Math.abs(metresPerPx(0, 0) - 156543.03) < 0.01);
  assert.ok(Math.abs(metresPerPx(0, 1) * 2 - metresPerPx(0, 0)) < 1e-9);
  assert.ok(metresPerPx(60, 10) < metresPerPx(0, 10) * 0.51);
});

test("scaleLength picks the longest 1-2-5 length that fits", () => {
  assert.equal(scaleLength(180), 100);
  assert.equal(scaleLength(240), 200);
  assert.equal(scaleLength(999), 500);
  assert.equal(scaleLength(1000), 1000);
});
