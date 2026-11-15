# Home and page layout: implementation spec

Label: ready-for-agent
Status: done

Source: the user's request on 2026-11-15 and their answers (page width 1280 px; option A for recent races: merge `races.csv` with parkruns and mark parkrun rows "parkrun"; every other part of the dashboard stays as it is). Terms are in `GLOSSARY.md` at the root, product background in `PRODUCT.md`.

## Problem Statement

The dashboard page is up to 1560 px wide, while the header bar spans the whole window, so on a wide screen the brand and navigation sit far from the content. On the home page the top band splits training load, weekly volume and race prediction into three narrow columns (1.35 / 1 / 0.95), so the training load chart is cramped. On the 5K plan, plan review and parkrun pages the tables are capped at 980 px and leave an empty strip on the right. The recent races table reads only `races.csv`, so a runner who mostly runs parkruns and keeps no `races.csv` sees an empty table, even though the parkruns are already detected for race prediction.

## Solution

- The page width drops one step, to 1280 px, and the header box uses the same width and padding, so the brand lines up with the content.
- Home band: training load spans the full width in its own row; weekly volume and race prediction share the next row 50/50 with a divider.
- Tables on the 5K plan, plan review and parkrun pages span the full page width. Prose keeps its existing `ch` limits.
- Recent races merge `races.csv` with parkruns detected from the analysis database, newest first; parkrun rows are marked "parkrun".

Everything else (the week strip, aerobic fitness, the lower row with long runs and recent races, the activity list and the detail page, the mobile single column) stays as it is.

## User Stories

**Page width**

1. As a runner on a wide screen, I want the page narrower, so that lines and charts are easier to scan.
2. As a runner, I want the header to line up with the page, so that the brand and navigation sit above the content and not at the window edges.

**Home band**

3. As a runner, I want the training load chart across the full width, so that I can read weeks of load balance easily.
4. As a runner, I want weekly volume and race prediction side by side at equal width, so that neither is squeezed.
5. As a runner on a phone, I want the band to stay one column, as today.

**Tables**

6. As a runner, I want the tables on the 5K plan, plan review and parkrun pages to use the full page width, so that columns are not crammed while the right side is empty.

**Recent races**

7. As a runner who runs parkrun, I want my parkruns in the recent races table, so that it is not empty without `races.csv`.
8. As a runner, I want parkrun rows marked "parkrun", so that I can tell them from the races I listed by hand.
9. As a runner, I want a race I listed in `races.csv` to appear once, with my own note, even when it is also detected as a parkrun.
10. As a runner without `races.csv`, I still want the hint on how to add it, shown together with my parkruns.
11. As a runner with a broken `races.csv`, I still want the warning naming the line, shown together with my parkruns.

## Implementation Decisions

**What does not change**

- No Rust change, no schema change, no new config key.
- The parkrun rule stays the one in `running.races.parkruns` (Saturday, local start 7–9 h, run-only distance 4800–5400 m); it is reused, not re-derived.
- `race_predictions` is not changed: its basis and its parkrun fallback stay as they are.
- The run kind in the activity list stays as it is.

**Dashboard styles** (`analysis/src/running/dashboard/styles/tailwind.css`, compiled with `scripts/build_css.py`)

- `.page`: `max-w-[1280px]` (was 1560).
- `.topbar`: its inner box uses the same `max-w-[1280px] mx-auto` and the same horizontal padding as `.page`; the bottom rule may still span the window. If the markup needs a wrapper inside `<header>`, add it in `index.html`. The 980 px breakpoint keeps its smaller padding for both.
- `.a-band`: two columns `1fr 1fr`. `.band-load` spans both columns in row 1 with a bottom rule; `.band-volume` is column 1 and `.band-predict` column 2 of row 2, with the existing left divider on `.band-predict`. Padding is adjusted so the first column of each row lines up with the page edge.
- The training load chart keeps a readable height at full width: its height does not grow with its width (fixed CSS height, or a viewBox ratio that matches the new width; the implementer picks one and records it).
- The 980 px caps are removed from `.plan-paces table, .plan-week table`, `.review` and `.parkruns`; tables there use `w-full`. Prose blocks keep their `ch` limits.

**Analysis package `running.races`**

- `race_list(today, root)` merges the past races from `races.csv` with `parkruns(...)` over the whole history up to `today`.
- Each `Race` in the list gains `source: "races" | "parkrun"`. Parkrun rows have `note: "parkrun"` and `all_out: true`.
- Deduplication: when a parkrun has the same `activity_id` as a `races.csv` row, the `races.csv` row wins and the parkrun is dropped. Rows without `activity_id` are not deduplicated.
- Order: newest first by date; within the same date, `races.csv` first.
- Without an analysis database, or without the `activities` table, the list is the `races.csv` races as today.
- `races_error` keeps its meaning: a missing or invalid `races.csv` is still reported, and parkruns are listed alongside.
- `method.description` states both sources, the parkrun rule and the deduplication.

**Dashboard frontend** (`static/races.js`)

- The section head subtitle becomes "races.csv + parkrun".
- Rows from parkrun show "parkrun" in 备注 (note).
- Missing `races.csv`: the folded hint is shown above the table, and the table still lists the parkruns. Invalid `races.csv`: the warning is shown above the table, same. The empty message appears only when both sources are empty.
- `LIMIT` stays 10 (see Further Notes).

**Docs**

- `README.md`: the recent races part says it merges `races.csv` with parkruns.
- `GLOSSARY.md`: a parkrun entry (there is none yet; the run kind entry mentions it) that says what counts as a parkrun and that parkruns are shown in recent races.
- Any design doc that records the page width or the band layout: update the numbers.

## Testing Decisions

Verify only through external behaviour, as in previous phases.

- **Recent races** go through Seam 3 (pytest + FastAPI `TestClient`, synthetic `running.sqlite`, synthetic `races.csv`), in `tests/test_predictions_api.py`:
  - Without `races.csv`, parkruns are listed with `source = "parkrun"` and `note = "parkrun"`, and `races_error` still says the file is missing.
  - With `races.csv` and parkruns, the list is merged newest first.
  - A `races.csv` row with the same `activity_id` as a parkrun appears once, with `source = "races"` and its own note.
  - An invalid `races.csv` still reports its error, and parkruns are still listed.
  - Without an analysis database, the list equals the `races.csv` races.
  - The `method` text names both sources.
- **Layout** has no automated test, as before; the CSS build check (`build_css.py --check`) must pass. The last ticket is a check by eye in the browser at a wide window and at a phone width.
- The synthetic data generators extend the existing `tests/synthetic*.py` helpers; no new parallel set.
- Tests never run on the real data directory; tests always set `RUNNING_DATA_DIR` to a temporary directory.

## Out of Scope

- Changing the week strip, aerobic fitness, the lower row (long runs, recent races placement), the activity list or the detail page.
- Changing the parkrun rule, race prediction or the run kind.
- A full-width mode switch or a user setting for the page width.
- Paging or filtering the recent races table.

## Further Notes

- **Crowding**: with a parkrun most Saturdays, the 10-row recent races table may show mostly parkruns and push older `races.csv` races out. The user accepted option A; if it bothers them on real data in the last ticket, a follow-up can raise `LIMIT` or always keep the newest `races.csv` races.
- **Privacy**: per `CLAUDE.md`, checks on real data report only aggregate numbers (row counts by source); activity names are not echoed.
- The user confirmed the plan on 2026-11-15.

## Deviations during implementation (accepted)

- `aerobic.js` race markers keep only rows with `source == "races"`, so the aerobic chart is unchanged by the parkruns now in `/api/races`.
- `load.js` keeps the 560-wide viewBox below 980 px. The breakpoint is read with `matchMedia` when the chart renders, so resizing the window across 980 px applies after a reload.
- `method.params` of the race list gains `sources` and the parkrun rule params (`parkrun_weekday`, `parkrun_m`, `parkrun_hours`).
