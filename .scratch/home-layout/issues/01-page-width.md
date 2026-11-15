# 01: Page width 1280 px, header aligned, tables full width

**What to build:** The page drops from 1560 px to 1280 px, the header box uses the same width and padding as the page, and the tables on the 5K plan, plan review and parkrun pages fill the page width instead of stopping at 980 px.

**Blocked by:** none

**Status:** done

Source: User Stories 1, 2 and 6, and "Dashboard styles" under Implementation Decisions, in the [implementation spec](../spec.md).

- [x] `.page` uses `max-w-[1280px]`
- [x] The header's brand, navigation and sync line sit in a box with the same `max-w-[1280px] mx-auto` and horizontal padding as `.page` (add an inner wrapper in `index.html` if needed); the bottom rule may span the window
- [x] At the 980 px breakpoint both keep the smaller padding they have today
- [x] The 980 px caps are removed from `.plan-paces table, .plan-week table`, `.review` and `.parkruns`; the tables there are `w-full`
- [x] Prose blocks keep their `ch` limits
- [x] `static/style.css` is rebuilt with `uv run python scripts/build_css.py`, and `--check` passes
- [x] Browser check with synthetic data or the running dashboard: at a 1600 px window the header and page edges line up on `#/`, `#/runs`, `#/plan`, `#/review` and `#/parkruns`; the three tables reach the right edge; nothing overflows at 390 px
- [x] `ruff format --check`, `ruff check` and `pytest` pass

## Outcome (implementation notes)

- `index.html`: `<header class="topbar">` now wraps brand, nav and sync line in `<div class="topbar-in">`. `.topbar` keeps only the bottom rule (spans the window); `.topbar-in` carries the flex layout, `max-w-[1280px] mx-auto`, `px-8` and `h-14`. At 980 px `.topbar-in` gets `px-4.5 gap-3.5`, as `.page` gets `px-4.5`.
- `.page`: `max-w-[1280px]`.
- `.plan-paces table, .plan-week table` are `w-full` (was `max-w-[980px]`); the `max-w-[980px]` rules on `.review` and `.parkruns` are dropped, so their tables take the global `table { w-full }`. Prose `ch` limits are untouched.
- No other doc recorded the 1560 px or 980 px widths.
- Browser check left to the orchestrator.
- Browser check (outcome): checked on the running dashboard at a 2560 px wide viewport and at 390 px. Header and page are aligned (1280 px wide); the load chart is 1216 x 190 px; volume and prediction are 608 px each; the plan, review and parkrun overview tables are full width. At 390 px the band is one column (load, volume, prediction). The mobile horizontal overflow (scrollWidth 538) comes from the week strip (`.ws-days`, `.ws-sum`, `.ws-side`), which this spec does not touch; out of scope. The `pr-splits` table on the parkrun page stays narrow (it is not one of the listed tables).
