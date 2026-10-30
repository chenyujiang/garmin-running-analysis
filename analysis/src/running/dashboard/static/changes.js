// "Changed since last read" red dots (ticket 15).
//
// The browser's localStorage holds the last *read* value of each headline
// number, as the text shown on the page (so rounding noise never counts as a
// change). Nothing is written on the server.
//
// - A number whose shown text differs from its read value gets a red dot.
// - A number with no read value yet (first open, or a newly added number) gets
//   no dot; its current text is stored as the read value straight away.
// - "全部标为已读" stores every current value as read and clears all dots.
// - Read values only move on that click, so dots stay across reloads until then.

import { h } from "./dom.js";

export const STORAGE_KEY = "running-dashboard.seen.v1";

/** Pure tracker. `storage` needs getItem/setItem (localStorage in the browser). */
export function createTracker(storage) {
  let seen = load(storage);
  const current = new Map();
  const changed = new Set();
  const listeners = [];
  const notify = () => listeners.forEach((fn) => fn([...changed]));

  return {
    /** Report the value a headline number shows now. */
    observe(key, value) {
      const v = String(value);
      current.set(key, v);
      if (!(key in seen)) {
        seen[key] = v;
        save(storage, seen);
      }
      const was = changed.has(key);
      const isChanged = seen[key] !== v;
      if (isChanged) changed.add(key); else changed.delete(key);
      if (was !== isChanged) notify();
      return isChanged ? { changed: true, previous: seen[key] } : { changed: false };
    },
    changedKeys() {
      return [...changed];
    },
    markAllRead() {
      seen = { ...seen, ...Object.fromEntries(current) };
      save(storage, seen);
      changed.clear();
      notify();
    },
    /** `fn(changedKeys)` runs whenever the set of changed numbers changes. */
    subscribe(fn) {
      listeners.push(fn);
    },
  };
}

function load(storage) {
  try {
    const parsed = JSON.parse(storage.getItem(STORAGE_KEY) ?? "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function save(storage, seen) {
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(seen));
  } catch {
    // Storage unavailable (private mode, quota): dots just never appear.
  }
}

// ---- Browser glue ---------------------------------------------------------

let tracker = null;
let dots = [];

function pageTracker() {
  if (!tracker) {
    let storage;
    try {
      storage = globalThis.localStorage;
    } catch {
      storage = null;
    }
    tracker = createTracker(storage ?? { getItem: () => null, setItem() {} });
  }
  return tracker;
}

/** Register a headline number shown in `el` under `key`; `shown` is its text.
 *  Appends a red dot to `el` when the number changed since the last read.
 *  Returns `el`. */
export function watch(el, key, shown) {
  const r = pageTracker().observe(key, shown);
  if (r.changed) {
    const dot = h("span", { class: "new-dot", title: `上次标为已读时是 ${r.previous}`,
      "aria-label": `有变化，上次标为已读时是 ${r.previous}` });
    el.append(dot);
    dots.push(dot);
  }
  return el;
}

/** The "全部标为已读" button; shows how many numbers changed, hidden when none. */
export function markAllReadButton() {
  const t = pageTracker();
  const btn = h("button", { type: "button", class: "mark-read", hidden: "" });
  const update = (keys) => {
    btn.hidden = keys.length === 0;
    btn.replaceChildren(h("span", { class: "new-dot" }), `${keys.length} 处有变化 · 全部标为已读`);
  };
  btn.addEventListener("click", () => {
    t.markAllRead();
    dots.forEach((d) => d.remove());
    dots = [];
  });
  t.subscribe(update);
  update(t.changedKeys());
  return btn;
}
