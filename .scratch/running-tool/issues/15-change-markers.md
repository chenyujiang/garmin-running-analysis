# 15: "Changed since last visit" red dots

**What to build:** When the user opens the dashboard, numbers that changed since the last visit have a red dot next to them; one click on "全部标为已读" (mark all as read) clears every dot.

**Blocked by:** 09 (training load: TRIMP and CTL/ATL/TSB in the dashboard load column), 10 (run/walk classification and weekly volume in the dashboard volume column), 14 (race prediction and races)

**Status:** done

Source: User Story 59 in the [implementation spec](../spec.md).

- [x] The browser's localStorage records the last seen values; the server writes nothing
- [x] A red dot shows when a headline number in load, volume or prediction changes
- [x] "Mark all as read" stores the current values as read, and every red dot disappears
- [x] No red dots on the first visit (empty localStorage)
- [x] Browser check: after changing the synthetic data, a refresh shows red dots, and marking as read removes them

## Outcome

- New module `analysis/src/running/dashboard/static/changes.js`: pure logic `createTracker(storage)` (`observe(key, shown)`, `changedKeys()`, `markAllRead()`, `subscribe(fn)`), browser glue `watch(el, key, shown)` (on a change it appends `span.new-dot` to `el`, with the last read value in its title) and `markAllReadButton()` (left of the sync time in the top bar, "N 处有变化 · 全部标为已读" (N changes · mark all as read), hidden when nothing changed).
- localStorage key `running-dashboard.seen.v1`, value `{key: shown text}`. The comparison uses the text shown on the page, not the raw float, so rounding jitter is not a change.
- Tracked numbers: load `load.ctl/atl/tsb`; volume `volume.this_week/last_week/rolling_7d` (km, one decimal); prediction `predict.5k/10k/half/marathon` (the prediction column).
- Decision: on the first visit (or for a newly appearing number) with no read value, no red dot is shown and the current value becomes the read baseline right away; otherwise there would never be anything to compare against after the first visit. After that the read values change only when "mark all as read" is clicked, so the dots survive a refresh until the button is clicked.
- When localStorage is unavailable or its content is corrupt, no dots show and nothing errors.
- Tests: `analysis/tests/js/changes.test.mjs` (`node --test`, 8 cases), run inside `uv run pytest` by `tests/test_changes_js.py`; skipped when Node is not installed.
- Browser check (temporary synthetic data directory, port 8795): 0 dots on the first visit; after changing the synthetic data a refresh shows 10 dots and a "10 处有变化" (10 changes) button; clicking it removes all dots and hides the button, and a further refresh still shows 0.
