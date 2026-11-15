# 12: Aerobic fitness trend chart

**What to build:** The dashboard's second screen is a full-width aerobic fitness trend chart. The vertical axis is pace at the reference heart rate, faster is higher; dots are weekly medians and the line is the 4-week rolling median; below it is a sub-chart of the weekly average temperature. The user can switch between six months, 1 year, 2 years and everything; on hover a crosshair reads out that week's dates, pace and temperature. A "how aerobic fitness is computed" note sits next to it.

**Blocked by:** 11 (aerobic fitness computation and interface)

**Status:** done

Source: User Stories 53–56 and 58, and "Dashboard" under Implementation Decisions, in the [implementation spec](../spec.md).

- [x] Hand-written SVG, no chart library; the main chart and the temperature sub-chart are left-aligned
- [x] Switching the range calls the aerobic endpoint's range parameter
- [x] Weeks without enough data have no dot, and the line breaks at empty weeks without interpolation
- [x] The crosshair readout follows prototype variant C
- [x] The visuals follow prototype variant A: at most 2 editorial annotations per chart, numbers in tabular-nums
- [x] Check all four ranges and the crosshair readout in the browser with synthetic data

## Outcome

- The endpoint is unchanged: ticket 11's `GET /api/aerobic?range=&today=` already gives every field needed, so there are no new Seam 3 tests; the frontend has no test seam and relies on a browser check.
- The code is in `static/aerobic.js` (`aerobicSection()`) and draws its own SVG without touching the shared `svg.js` (which joins lines across nulls). The main chart and the temperature sub-chart share width and left/right margins, so their plot areas line up.
- The vertical axis is inverted (faster is higher), with m:ss ticks. Dots are weekly medians; the unfinished current week is a hollow dot. The rolling line breaks at empty weeks, and an isolated rolling point is drawn as a short dash.
- The default range is 1 year; switching re-requests with the page's `?today=`, and stale responses are dropped.
- Two annotations: the week with the fastest 4-week rolling value; the hottest week (marked only when it is more than 5°C above the median temperature, with a note that temperature is not corrected).
- The crosshair snaps to the nearest week and reads out: date range, weekly median, 4-week rolling value, number of valid runs, temperature.
- Race markers are not shown yet: there is no races endpoint yet.
- Browser check: 140 weeks of synthetic data; all four ranges and the crosshair readout work.
