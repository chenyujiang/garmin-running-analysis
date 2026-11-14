# 05: Daily summary sync

**What to build:** `runsync sync` also pulls the daily summaries (resting heart rate and so on) and writes them into the raw archive and the analysis database. It re-pulls the last 7 days every time, to pick up the incomplete current day and Garmin's later corrections.

**Blocked by:** 04 (Personal API activity sync)

**Status:** done

Source: User Story 15 in the [implementation spec](../spec.md).

- [x] Daily summaries are requested in 7-day ranges and stored in the raw archive as one JSON file per day
- [x] The backfill starts at 2021-08; after that every sync re-pulls the last 7 days and overwrites the files of the same name
- [x] `daily_wellness` has one row per day, written with an upsert; `rebuild` can also rebuild this table from the raw archive
- [x] Empty HRV and sleep responses stay only in the raw archive; no tables are created for them
- [x] Seam 1 test: writing the same day twice is an upsert
- [x] Seam 2 test: the daily summaries of the last 7 days are overwritten, and earlier ones are not re-pulled

## Outcome

- **Endpoint**: `GET /usersummary-service/v2/dailysummaries?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD` (closed range, taken from `get_daily_summaries` in the official `garmin-connect-personal-api-python` 1.0.0); the response is `{"data": [...]}`, one row per day that has data. `ActivitySource` gains `daily_summaries(start, end) -> String`.
- **Raw archive**: `raw/personal_api/daily_summaries/<YYYY-MM-DD>.json`, holding that day's row from the response, stored as is (`RawValue`, fields not reordered). A day that was requested but had no data gets `null`, so resuming does not keep fetching the empty stretch from 2021-08 to 2021-10.
- **Order**: daily summaries are pulled after the activity sync (not at all if the activities were rate-limited). First the last 7 days `today-6..today` are re-pulled (`today` is the local date, `SyncOptions.today`), then 7-day ranges from `today-13..today-7` back to 2021-08-01, newest first; a range whose daily files all exist is skipped. On a rate limit or an error it stops, keeps the files and rows already written, and `sync_runs` records the matching outcome.
- **`daily_wellness`** (migration `0004`): primary key `calendar_date`, `INSERT OR REPLACE`. Columns: resting/minimum/maximum heart rate, steps and walking distance, total/active/resting calories, moderate and vigorous minutes, average stress, Body Battery minimum/maximum, average respiration rate. Values are stored as they come (integers as INTEGER, decimals as REAL); missing fields are NULL. `null` days get no row.
- **HRV and sleep**: not requested separately, no tables. The spec's raw archive layout lists only `daily_summaries/`; the user does not wear the watch at night, so there is no HRV/sleep data (the spec's "Out of Scope" section), and a separate backfill would triple the request count. The whole JSON row of each daily summary is archived as is, so they can be taken from the archive later if needed.
- **rebuild**: rebuilds `daily_wellness` from `daily_summaries/*.json`; broken files count as skipped; stdout adds `N daily summaries`.
- Tests: Seam 2 `importer/tests/daily_sync.rs` (6 tests); Seam 1 `tests/rebuild.rs` gains 2 (rebuild loads them; writing the same day twice is an upsert). The first backfill is about 270 requests; how long it takes depends on `personal_api_interval_s`.
