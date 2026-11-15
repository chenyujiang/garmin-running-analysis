# 03: Recent races merge races.csv with parkruns

**What to build:** `GET /api/races` lists past races from `races.csv` and parkruns detected in the analysis database together, newest first. Parkrun rows are marked "parkrun"; a race listed in `races.csv` appears once. The home page's recent races table shows both.

**Blocked by:** none

**Status:** open

Source: User Stories 7–11, and "Analysis package `running.races`" and "Dashboard frontend" under Implementation Decisions, and Testing Decisions, in the [implementation spec](../spec.md).

- [ ] `race_list` merges `races.csv` past races with `parkruns(...)` over the whole history up to `today`, reusing the existing parkrun rule
- [ ] Each race gains `source: "races" | "parkrun"` (in the `Race`/`RaceList` types and the API response); parkrun rows have `note: "parkrun"`, `all_out: true`
- [ ] Same `activity_id` in both: the `races.csv` row wins
- [ ] Newest first; on the same date `races.csv` first
- [ ] Without an analysis database or `activities` table, the list equals the `races.csv` races
- [ ] `races_error` is unchanged in meaning; parkruns are listed even when `races.csv` is missing or invalid
- [ ] `method.description` names both sources, the parkrun rule and the deduplication
- [ ] `race_predictions` is not changed
- [ ] `static/races.js`: subtitle "races.csv + parkrun"; the missing-file hint and the invalid-file warning sit above a table that still lists parkruns; the empty message only when both sources are empty; `LIMIT` stays 10
- [ ] Seam 3 tests in `tests/test_predictions_api.py`, per the spec's Testing Decisions, with the existing synthetic helpers
- [ ] `ruff format --check`, `ruff check` and `pytest` pass
