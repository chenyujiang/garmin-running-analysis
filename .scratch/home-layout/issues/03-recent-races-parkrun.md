# 03: Recent races merge races.csv with parkruns

**What to build:** `GET /api/races` lists past races from `races.csv` and parkruns detected in the analysis database together, newest first. Parkrun rows are marked "parkrun"; a race listed in `races.csv` appears once. The home page's recent races table shows both.

**Blocked by:** none

**Status:** done

Source: User Stories 7–11, and "Analysis package `running.races`" and "Dashboard frontend" under Implementation Decisions, and Testing Decisions, in the [implementation spec](../spec.md).

- [x] `race_list` merges `races.csv` past races with `parkruns(...)` over the whole history up to `today`, reusing the existing parkrun rule
- [x] Each race gains `source: "races" | "parkrun"` (in the `Race`/`RaceList` types and the API response); parkrun rows have `note: "parkrun"`, `all_out: true`
- [x] Same `activity_id` in both: the `races.csv` row wins
- [x] Newest first; on the same date `races.csv` first
- [x] Without an analysis database or `activities` table, the list equals the `races.csv` races
- [x] `races_error` is unchanged in meaning; parkruns are listed even when `races.csv` is missing or invalid
- [x] `method.description` names both sources, the parkrun rule and the deduplication
- [x] `race_predictions` is not changed
- [x] `static/races.js`: subtitle "races.csv + parkrun"; the missing-file hint and the invalid-file warning sit above a table that still lists parkruns; the empty message only when both sources are empty; `LIMIT` stays 10
- [x] Seam 3 tests in `tests/test_predictions_api.py`, per the spec's Testing Decisions, with the existing synthetic helpers
- [x] `ruff format --check`, `ruff check` and `pytest` pass

## Outcome (implementation notes)

- `race_list` reads `races.csv`, then `parkruns(db, run_walk, date.min, today)`; drops parkruns whose `activity_id` is in `races.csv`; two stable sorts give newest first, `races.csv` first on the same date.
- Listed rows are a `ListedRace` (`Race` + `source`); `RaceList.races` uses it. `read_races`, `parkruns` and `race_predictions` keep plain `Race`, so predictions are unchanged.
- `method.params` gains `sources` and the parkrun rule parameters.
- `races.js`: subtitle "races.csv + parkrun"; the missing hint (shorter line when parkruns exist) or the invalid warning sits above the table; the empty message only when the list is empty and `races.csv` had no error.
- `aerobic.js` also reads `/api/races` for its race markers; it now keeps only `source == "races"` rows, so the aerobic chart is unchanged (spec: aerobic fitness stays as it is).
- No JS unit test: the `races.js` change is view branching only. Six Seam 3 tests added; the existing race list shape test gains `source`.