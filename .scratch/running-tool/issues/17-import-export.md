# 17: Import the Garmin account data export

**What to build:** a new command `runsync import-export <zip>`: store the Garmin account data export package as is in the raw archive, and parse it into the analysis database, so that the machine has the history from 2021-08 onwards without going through the API. Later `runsync sync` runs only fill in new data after the export date and do not re-pull what the export package already contains. Fully offline.

**Blocked by:** 05 (daily summary sync), 06 (garminconnect metrics), 07 (rate-limit cooldown and credential failure handling)

**Status:** done

Source: User Stories 9–11 and 31 in the [implementation spec](../spec.md); this ticket changes the rule "the export package is only archived, not parsed" under "Raw archive layout" in the spec.

## Export package structure (from the user's real export package of 2026-10, structure only)

- `DI_CONNECT/DI-Connect-Fitness/<email>_<n>_summarizedActivities.json`: summaries of all activities (about 1100, from 2021-08), with fields `activityId`, `activityType`, `beginTimestamp`, `startTimeLocal`, `startTimeGmt`, `distance`, `duration`, `avgHr`, `maxHr`, `elevationGain` and so on. **Units are not SI** (e.g. distance may be cm, duration ms); confirm during implementation by cross-checking distance, duration and pace.
- `DI_CONNECT/DI-Connect-Uploaded-Files/UploadedFiles_0-_Part{1,2,3}.zip`: zips inside the zip, about 17770 `.fit` files in total, mixed with daily monitoring FIT files; take only activity files by `file_id`'s `type`, then map them to `activityId` (by file name, or session start time against `beginTimestamp`; confirm during implementation).
- `DI_CONNECT/DI-Connect-Aggregator/UDSFile_*.json`: daily summaries (resting heart rate, steps, stress, Body Battery and so on).
- `DI_CONNECT/DI-Connect-Metrics/`: `MetricsMaxMetData_*` (vo2Max), `RunRacePredictions_*` (5K/10K/half/marathon predictions), `TrainingHistory_*` (training status, load).
- Everything else (sleep, profile and so on) is only archived, not parsed.

## Requirements

- [x] `runsync import-export <zip>`: copy the zip as is to `raw/export/<export date>/` (how the export date is determined goes in the outcome), then parse from that archived copy. Importing the same package again is idempotent; importing a newer package overwrites old data with new
- [x] Activity summaries go into `activities`, converted to SI, with time columns following the format in `conventions.md`; activity types match the Personal API's type keys (map them if they differ)
- [x] Activity FIT files are parsed into `records` and `laps`, reusing the existing FIT parsing; non-activity FIT files are skipped; FIT files that fail to parse are counted and skipped without aborting
- [x] UDS daily summaries go into `daily_wellness`; the three Garmin metrics go into `garmin_metrics`, with NULL for fields that do not match
- [x] When the same activity or day has both export data and Personal API / garminconnect data, the API data wins
- [x] `runsync rebuild` also rebuilds this data from `raw/export/`, with the same result as importing directly
- [x] `runsync sync`: activities already in the export package count as "already there" (paging stops, no FIT or detail download, the last-7-days refresh rule unchanged); days already covered by the export package are no longer backfilled for daily summaries; the same for garminconnect backfill
- [x] At the end the command prints a summary: counts per kind of entry, number of skipped non-activity FIT files, number of parse failures, date range of the data. No GPS coordinates
- [x] Seam 1 tests: a hand-written mini export package fixture (synthetic JSON + small synthetic FIT, no real GPS, no email), asserting row counts per table, units, idempotence, API precedence, and that rebuild matches
- [x] Seam 2 tests: after an import, `sync` no longer requests activities and days the export package already has
- [x] Integration tests reading the real export package are marked `#[ignore]` and read from the data directory
- [x] README documents the import steps

## Safety

- The real export package contains GPS and an email address and stays out of git (the repository's `.gitignore` already has `*.zip`). Fixtures are entirely hand-written and synthetic.
- Manual verification with the real package uses only a temporary `RUNNING_DATA_DIR` (outside the repository), looks only at aggregate numbers, and deletes the temporary directory afterwards. `%USERPROFILE%\running-data` is not touched.
- The export package is untrusted data: guard against zip path traversal while parsing (never write files by entry name), and never run anything in an extracted directory.

## Outcome

Implemented in `importer/src/export.rs` (`runsync::export`); everything below was checked against the real package of 2026-10 (aggregate numbers only).

- **Export date**: the latest day among the modification times of all entries in the package. All entries in the real package are 2026-10-30, so it is stored at `raw/export/2026-10-30/<original file name>`. The package is never extracted to disk: entries are only read into memory and picked by name, and the nested `UploadedFiles_*.zip` are opened in memory too; any single entry over 1 GiB is not read.
- **Activity units** (cross-checked against the FIT session's distance, duration and calories): `beginTimestamp` is UTC milliseconds; `startTimeLocal` is the local wall-clock time written as if it were UTC, in milliseconds; `duration`/`movingDuration`/`elapsedDuration` are ms; `distance` and `elevationGain/Loss` are cm; `avgSpeed`/`maxSpeed` must be multiplied by 10 to get m/s; `calories` must be divided by 4.19 to get kcal. The values of `activityType` (`running`, `track_running`, `walking` and so on) match the Personal API's type keys, so no mapping is needed. `timeZoneId` is only a Garmin-internal numeric id, so `time_zone` is left NULL.
- **Matching FIT to activities**: FIT files contain no activityId; they are matched by session start time (Unix seconds) == `beginTimestamp / 1000` (1096 of the 1097 activity FIT files in the real package matched). FIT files whose `file_id.type` is not activity are counted as "not an activity" and skipped; those matching no activity are counted as "matching no activity"; those that fail to parse are counted and skipped.
- **Garmin metrics**: `MetricsMaxMetData` takes only rows with `sport == RUNNING` (`vo2MaxValue`); `RunRacePredictions` writes the four race predictions; `TrainingHistory` has only the training status, no acute/chronic load, so those columns stay NULL. With several rows on the same day, the row with the latest update time wins. The training status vocabulary differs from the API: the export package writes `PRODUCTIVE`, the API `PRODUCTIVE_1`; later (2026-10-31, see 18) the API's numeric suffix is stripped on write, and both sides store `PRODUCTIVE`.
- **Precedence**: data already archived from the API (`raw/personal_api/activities/<id>.json|.fit`, non-`null` `raw/personal_api/daily_summaries/<date>.json`, `raw/garminconnect/<metric>/<date>.json`) wins, and the corresponding part of the export package is simply not loaded, so the result does not depend on load order. Several export packages are loaded from oldest to newest export date; after importing a package, the archived packages whose export date is not earlier than it are loaded again, so a newer package overwrites an older one. Importing the same package again is idempotent. `rebuild` loads all packages under `raw/export/` after the API files, with the same result as importing directly (the Seam 1 test compares `activities`, `records`, `laps`, `daily_wellness` and `garmin_metrics` row by row); when one package fails to load, `rebuild` rolls back that package and continues.
- **How sync handles it**: activities already in the `activities` table (whether from the API or the export package) count as "already there": paging stops as usual, and no detail or FIT is downloaded; the last-7-days refresh is unchanged. New migration `0006_export_packages.sql` adds the table `export_packages`, recording each package's export date and the first day of its daily summaries and of its metrics; `db::export_covers` decides whether a day falls between some package's "first day..export date". The daily summary backfill treats those days as archived; the garminconnect backfill skips them. Today's snapshot and the last 7 days are requested as usual.
- **Real package results** (temporary data directory, about 66 s, deleted after verification): 1098 activities; 17770 FIT files in total, of which 1096 activity FIT files loaded, 1 matched no activity, 16673 non-activity skipped, 0 parse failures; daily summaries for 1912 days (2021-08-06..2026-10-30); Garmin metrics for 1909 days (2021-08-07..2026-10-30). A later `runsync rebuild` also rebuilt successfully.
