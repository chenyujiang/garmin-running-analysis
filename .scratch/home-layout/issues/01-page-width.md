# 01: Page width 1280 px, header aligned, tables full width

**What to build:** The page drops from 1560 px to 1280 px, the header box uses the same width and padding as the page, and the tables on the 5K plan, plan review and parkrun pages fill the page width instead of stopping at 980 px.

**Blocked by:** none

**Status:** open

Source: User Stories 1, 2 and 6, and "Dashboard styles" under Implementation Decisions, in the [implementation spec](../spec.md).

- [ ] `.page` uses `max-w-[1280px]`
- [ ] The header's brand, navigation and sync line sit in a box with the same `max-w-[1280px] mx-auto` and horizontal padding as `.page` (add an inner wrapper in `index.html` if needed); the bottom rule may span the window
- [ ] At the 980 px breakpoint both keep the smaller padding they have today
- [ ] The 980 px caps are removed from `.plan-paces table, .plan-week table`, `.review` and `.parkruns`; the tables there are `w-full`
- [ ] Prose blocks keep their `ch` limits
- [ ] `static/style.css` is rebuilt with `uv run python scripts/build_css.py`, and `--check` passes
- [ ] Browser check with synthetic data or the running dashboard: at a 1600 px window the header and page edges line up on `#/`, `#/runs`, `#/plan`, `#/review` and `#/parkruns`; the three tables reach the right edge; nothing overflows at 390 px
- [ ] `ruff format --check`, `ruff check` and `pytest` pass
