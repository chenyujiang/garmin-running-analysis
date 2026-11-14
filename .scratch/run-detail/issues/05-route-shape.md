# 05: Route shape (SVG, no base map)

**What to build:** the detail page draws the route shape in SVG, marking start and finish, with a scale bar. No online base map is loaded, and the endpoint returns no absolute latitude or longitude.

**Blocked by:** 02

**Status:** done

Source: User Stories 15–16, "Route shape" under Implementation Decisions, and "Privacy" under Further Notes, in the [implementation spec](../spec.md).

- [x] Use only seconds with `lat`/`lon`; equirectangular projection onto a metric plane centred on the route, scaled as a whole into `[0, 1]`, keeping the aspect ratio
- [x] Douglas–Peucker simplification to at most 500 points
- [x] Return `x, y`, start and finish indices, scale (metres per unit); no latitude/longitude and no centre point
- [x] Without GPS, `route: null` with a reason
- [x] Frontend SVG: route, start and finish markers, scale bar; no map library
- [x] Seam 3 tests: made-up coordinates written in the test file; walk every number in the JSON and assert none is close to the original latitude/longitude; `x, y` in `[0, 1]`; aspect ratio kept; point count ≤ 500; null without GPS

## Outcome (implementation notes)

- Backend in the route block of `analysis/src/running/detail.py`, registering two entries in `SECTIONS`: `route` (the shape) and `route_unavailable` (the reason it is null).
- `route`: `x, y, start_index, finish_index, metres_per_unit, method`. Only seconds with `lat`/`lon` are queried (ordered by time); the query result is used only inside this block and does not go into `DetailInputs`.
  - Projection: equirectangular, origin at the centre of the latitude/longitude bounding box, east–west multiplied by the cosine of the centre latitude, earth radius 6371008.8 m.
  - Normalisation (our choice): subtract the minimum x and the northernmost y, then divide by the long side in metres; the long side fills `[0, 1]`, the short side starts at 0 and is not centred. **y increases southwards** (screen coordinates, north up), so the frontend uses it directly.
  - `metres_per_unit` = long side in metres of the points kept after simplification.
  - Simplification (our choice of details): Douglas–Peucker implemented with a priority queue, starting from both ends and each time splitting the segment whose farthest point is farthest from its chord, until 500 points or until all remaining points are within `tolerance_m = 0.5` m of their chord. The tolerance keeps straight stretches from being filled up to 500 points by floating-point noise; 0.5 m is far below GPS error and invisible. Start and finish are always kept, so `start_index = 0` and `finish_index = point count − 1`.
  - Pure Python (the analysis environment has no numpy); a test route with 3000 corners finishes in about 1 second.
- **Reason for null (our choice)**: the spec only says `route: null` with a reason and defines no field. We use the sibling `route_unavailable`: with no GPS fix at all (treadmill, no per-second records) it is "没有 GPS 记录（跑步机或室内活动）" (no GPS records (treadmill or indoor activity)); when all fixes are at the same spot it is "GPS 定位点不足，画不出形状" (too few GPS fixes to draw a shape); when there is a route it is null. Non-running activities with GPS still get a route (the spec's list of running-only fields does not include the route).
- `method.params`: `max_points, tolerance_m, projection`, with no coordinates.
- Frontend in the route block of `static/run.js`: `routeSection`, hand-written SVG (no map library, no base map), long side 420 px, the route as a black polyline, a hollow circle for the start and a filled circle for the finish; the scale bar at bottom left uses a round length close to 1/4 of the long side (reusing `niceStep` from `svg.js`, one more import line at the top of the file). Thin routes (such as a straight out-and-back) get a minimum width for the scale bar. Without a route it shows `route_unavailable`. CSS is in the ticket 05 block at the end of `style.css`.
- Tests `analysis/tests/test_detail_route.py` (Seam 3, 6 tests), synthetic data `add_route_run` in `tests/synthetic_route.py` (a new function that writes `lat`/`lon` per second along the track the test gives). The coordinates are made-up points written in the test file (open water in the Southern Ocean, with 4 decimals). Every test with a route walks all numbers in the whole response JSON and asserts none is within ±0.005° (about 500 m) of the original latitude or longitude (ignoring sign). The first version used ±0.5°; after merging ticket 03's per-second curves, heart-rate and altitude values happened to fall in that window, so the window was narrowed and the coordinates changed.
  - A 2000 × 1000 m rectangular loop: `x, y` in `[0, 1]`, x fills it and y spans 0.5 (aspect ratio 2:1), scale 2000 m, start and finish at the south-west corner, all four corners kept, straight stretches simplified to ≤ 10 points.
  - A 3000 m zigzag with a 2 m corner every second: exactly 500 points, scale 3000 m.
  - A straight out-and-back with no fix for the first 100 and last 50 seconds: only seconds with a fix are used, start and finish at the south end, the turnaround kept, scale 900 m.
  - A treadmill run with per-second records but no fixes, and an activity without per-second records: `route: null` plus a reason; a single fix: `route: null` plus "too few fixes".
- The frontend has no automated tests; visual checks with real data are done in ticket 08.
