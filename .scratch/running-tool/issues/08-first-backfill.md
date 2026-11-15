# 08: First full backfill

**What to build:** Complete the first full backfill with real data, so this machine holds the whole history since 2021-08, and confirm the import CLI works on real data. The history comes from the account data export (`runsync import-export`, offline); `runsync sync` fills in new data after the export date. This is a HITL ticket: the user runs the commands by hand.

**Blocked by:** 05 (daily summary sync), 07 (rate-limit cooldown and expired credentials), 17 (import the Garmin account data export)

**Status:** done

Source: User Stories 9–11, and "Data quality and cleaning" and "Temperature correction" under Out of Scope, in the [implementation spec](../spec.md).

- [x] Run `runsync import-export <zip>` (the archive is copied into `raw/export/`; the original in the repository root is ignored by `*.zip` and the user may delete it)
- [x] The user then runs `runsync sync` to fill in new data after the export date (if interrupted, running it again resumes)
- [x] The agent checks only summary information: row counts per table, the activity date range, the count per activity type, the number of skipped non-activity FIT files and the number of FIT files that failed to parse; it reads and prints no GPS coordinates
- [x] On a 429, follow the cooldown rule and do not retry
- [x] If the share of FIT files failing to parse is high, assess switching to `rustyfit` and record the conclusion in this ticket
- [x] After the backfill, open two new tickets in `.scratch/running-tool/issues/`: "Data quality and cleaning" and "Temperature correction"
- [x] Confirm `raw/` (including `raw/export/`) is part of the user's backups (confirmed by the user on 2026-10-31)

## Outcome

- **import-export** (2026-10-31, run by the agent with the user's permission): the archive is stored in `raw/export/2026-10-30/`. 1098 activities; 17770 FIT files, of which 1096 activity FIT files were loaded, 1 matched no activity, 16673 non-activity files were skipped and **0 failed to parse**, so there is no need to switch to `rustyfit`. Daily summaries cover 1912 days (2021-08-06..2026-10-30) and Garmin metrics 1909 days (2021-08-07..2026-10-30).
- **sync** (run by the user, 2026-10-31): two `sync_runs` rows, `personal_api` and `garminconnect` both `ok`, about 30 s in total, no 429 and no cooldown marker. 1 new activity (2026-10-31); daily summaries and Garmin metrics filled up to 2026-10-31. Days already covered by the export were not requested again.
- **Final row counts**: `activities` 1099 (running 1073, track_running 17, indoor_cardio 4, walking 2, strength_training 2, assistance 1), `records` 3363903, `laps` 11617, `daily_wellness` 1913, `garmin_metrics` 1910. Activity dates 2021-08-06..2026-10-31. 2 activities have no per-second records (logged in 18).
- **`config.toml`**: the user confirmed `hr_max = 193`, `hr_rest = 55`, `lthr = 170`, `effective_from = 2021-08-01`. Basis: the single-run maximum heart rate reached 193 on two days, in 2022 and 2025; Garmin's resting heart rate is unusable (the watch is only worn during the day), so the 10th percentile of the daily minimum heart rate is used instead; LTHR is the Garmin setting from the export, consistent with the average heart rate of the 10K and half-marathon races.
- Opened [18 Data quality and cleaning](18-data-quality.md) and [19 Temperature correction](19-temperature-correction.md).
