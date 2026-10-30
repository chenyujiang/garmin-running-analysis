// Seam: createTracker(storage) from static/changes.js.
// `storage` is anything with getItem/setItem (localStorage in the browser).

import { test } from "node:test";
import assert from "node:assert/strict";
import { createTracker } from "../../src/running/dashboard/static/changes.js";

function memoryStorage(initial = {}) {
  const m = new Map(Object.entries(initial));
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
  };
}

test("first open (empty storage): nothing is marked as changed", () => {
  const t = createTracker(memoryStorage());
  assert.equal(t.observe("load.ctl", "48").changed, false);
  assert.deepEqual(t.changedKeys(), []);
});

test("a number that differs from the last read value is changed; equal ones are not", () => {
  const storage = memoryStorage();
  const first = createTracker(storage);
  first.observe("load.ctl", "48");
  first.observe("volume.this_week", "21.3");
  first.markAllRead();

  const t = createTracker(storage);
  assert.deepEqual(t.observe("load.ctl", "51"), { changed: true, previous: "48" });
  assert.equal(t.observe("volume.this_week", "21.3").changed, false);
  assert.deepEqual(t.changedKeys(), ["load.ctl"]);
});

test("first open records the values it saw, so the next open can show changes", () => {
  const storage = memoryStorage();
  createTracker(storage).observe("load.ctl", "48");

  const t = createTracker(storage);
  assert.deepEqual(t.observe("load.ctl", "50"), { changed: true, previous: "48" });
});

test("a number not seen before is not marked, and is remembered without a click", () => {
  const storage = memoryStorage();
  const first = createTracker(storage);
  first.observe("load.ctl", "48");
  first.markAllRead();

  const second = createTracker(storage);
  second.observe("load.ctl", "48");
  assert.equal(second.observe("predict.5k", "21:30").changed, false);

  const third = createTracker(storage);
  assert.deepEqual(third.observe("predict.5k", "21:10"), { changed: true, previous: "21:30" });
});

test("mark all as read clears every mark and keeps the current values as read", () => {
  const storage = memoryStorage({ "running-dashboard.seen.v1": JSON.stringify({ a: "1", b: "2" }) });
  const t = createTracker(storage);
  t.observe("a", "10");
  t.observe("b", "20");
  assert.deepEqual(t.changedKeys(), ["a", "b"]);

  t.markAllRead();
  assert.deepEqual(t.changedKeys(), []);
  assert.equal(t.observe("a", "10").changed, false);
  assert.equal(createTracker(storage).observe("b", "20").changed, false);
});

test("changes keep showing on every open until marked as read", () => {
  const storage = memoryStorage({ "running-dashboard.seen.v1": JSON.stringify({ a: "1" }) });
  createTracker(storage).observe("a", "2");
  assert.deepEqual(createTracker(storage).observe("a", "2"), { changed: true, previous: "1" });
});

test("listeners hear about every change in the marked set", () => {
  const storage = memoryStorage({ "running-dashboard.seen.v1": JSON.stringify({ a: "1" }) });
  const t = createTracker(storage);
  const heard = [];
  t.subscribe((keys) => heard.push(keys));
  t.observe("a", "2");
  t.markAllRead();
  assert.deepEqual(heard, [["a"], []]);
});

test("unusable storage (throws or holds junk) means no marks and no errors", () => {
  const throwing = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); } };
  const t = createTracker(throwing);
  assert.equal(t.observe("a", "1").changed, false);
  t.markAllRead();

  const junk = memoryStorage({ "running-dashboard.seen.v1": "{not json" });
  assert.equal(createTracker(junk).observe("a", "1").changed, false);
});
