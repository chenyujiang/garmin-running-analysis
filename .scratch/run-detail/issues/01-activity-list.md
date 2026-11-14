# 01: Activity list: endpoint, page and routing

**What to build:** The dashboard gains an "全部活动" (all activities) page at `#/runs` that lists activities by start time, newest first, with filters for type and minimum distance, and pagination. This is the tracer bullet for this phase: it wires up hash routing, a new module, a new endpoint and Seam 3 tests.

**Blocked by:** none

**Status:** done

Source: User Stories 1–5, and `running/activities.py` and "Dashboard" under Implementation Decisions, in the [implementation spec](../spec.md).

- [x] `running/activities.py`: `activity_list(type_filter, min_distance_m, page, page_size, root)`, where `type_filter` is `running` (`RUNNING_TYPES`) or `all`
- [x] Each row holds `activity_id, activity_type, activity_name, start_time_local, distance_m, duration_s, running_pace_s_per_km` (running types only) and `avg_hr_bpm`; the total count is returned
- [x] `GET /api/activities?type=&min_km=&page=&page_size=`, `page_size` 1–200, default 50
- [x] `app.js` gains hash routing: `#/` home, `#/runs` list, `#/run/<id>` showing a placeholder for now; the page header gains an "全部活动" (all activities) link
- [x] `static/runs.js`: table, type and distance filters, pagination, styled like the table in variant A
- [x] Without an analysis database, the existing empty state is shown
- [x] Seam 3 tests: ordering, type filter, minimum distance, total count across pages, out-of-range `page_size` returns 422, `has_data=false` without a database

## Outcome (implementation notes)

- Module `analysis/src/running/activities.py`: `activity_list(type_filter="running", min_distance_m=None, page=1, page_size=50, root=None)`; endpoint `GET /api/activities?type=running|all&min_km=<float>&page=<int>&page_size=<int>` (`type` accepts only these two values, otherwise 422; `min_km ≥ 0`; `page ≥ 1`; `page_size` 1–200, default 50, 422 when out of range).
- Returns `has_data, type_filter, min_distance_m, page, page_size, total, activities[], method{name, description, params}`. `activities[]`: `activity_id, activity_type, activity_name, start_time_local, distance_m, duration_s, running_pace_s_per_km, avg_hr_bpm`. `min_distance_m` is in metres (the endpoint takes km and multiplies by 1000).
- Ordering: `start_time_local` descending, ties broken by `activity_id` descending, so pagination is stable.
- **`has_data` (our choice)**: true whenever the analysis database has any activity, regardless of filters. When filters leave no results, the frontend shows "没有符合筛选条件的活动" (no activities match the filters) instead of the empty state; the home page's empty state appears only when there is no database (or no activities in it).
- **Minimum distance (our choice)**: filters on `activities.distance_m` (Garmin's distance); when a minimum distance is set, activities without a distance are not listed.
- **Running pace**: reuses `runwalk.running_summaries`, computed only for running activities on the current page. For this it gained a keyword argument `activity_ids` (behaviour unchanged when omitted), so the 1500 activities are not all classified on every request. Without cadence data it falls back, as before, to Garmin's total distance and duration; non-running types get null.
- Frontend: `app.js` gains hash routing (`parseRoute`): `#/` (or empty, or an unknown hash) is home, `#/runs` the list, `#/run/<id>` a placeholder for now; on `hashchange` the state is re-read and rendered. Without a database every route shows the existing empty state. The page header gains navigation "首页 / 全部活动" (home / all activities), with the current page marked by `aria-current`; the brand name links back home.
- **Filters and page number live in the hash query string (our choice)**: `#/runs?type=all&min_km=10&page=2`, so they survive reloads and bookmarks.
- `static/runs.js`: `runsPage(query)`; the type switch reuses the `.seg` button group, distance is a dropdown (any, ≥5, 10, 15, 21, 30 km); 50 rows per page; date and name link to `#/run/<id>`. Activity types show a Chinese name (for the common ones); unknown types show the raw key. CSS is in the run-detail ticket 01 block at the end of `style.css`.
- Synthetic data: `insert_activity` in `tests/synthetic.py` gained two optional parameters, `activity_name` and `avg_hr_bpm`.
- Tests `analysis/tests/test_activities_api.py` (Seam 3, 12 functions, 14 after parametrisation): ordering and row fields; running pace excludes walking (same example as weekly volume, about 333 s/km), null for non-running types, Garmin totals when there are no records; type defaults to running, `all` lists everything, unknown type gives 422; minimum distance boundary (9999 m not listed, 10000 m listed) and activities without distance; pagination and totals; `page_size` 0 and 201 and `page` 0 give 422, 200 is fine; `has_data=false` without a database; `has_data` stays true when the filters match nothing.
