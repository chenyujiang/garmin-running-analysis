# 06: Small garminconnect script: `login` and the three Garmin metrics

**What to build:** The user runs `runsync login` once, types the Garmin password interactively, and only the tokens are saved. After that, `runsync sync` pulls Garmin's Training Status, VO2max and Race Predictor: one day per week during the backfill, and a snapshot of the current day on every later sync, to compare with our own numbers.

**Blocked by:** 04 (Personal API activity sync)

**Status:** done

Source: User Stories 4, 5 and 17, and "Small garminconnect script" under Implementation Decisions, in the [implementation spec](../spec.md).

- [x] A PEP 723 Python script lives in the Rust project and depends on `garminconnect`; the CLI calls it with `uv run --script`, with the script path fixed at compile time from `CARGO_MANIFEST_DIR`
- [x] The script's `login` subcommand reads the password with `getpass` and stores only the tokens in `secrets/garminconnect/`; the password never touches disk
- [x] The script's query subcommands print only JSON to stdout, and exit codes distinguish success, rate limit, authentication failure and other errors
- [x] The second data source implements the same data source trait, with a default request interval of 5 s
- [x] Raw JSON is stored in the raw archive per metric and per date; `garmin_metrics` has one row per day
- [x] First check whether the three metrics can be queried by date for history, and record the conclusion in this ticket; if not, store only daily snapshots
- [x] During development reuse the existing tokens instead of calling `login` repeatedly (the mobile login strategy has already been hit with 429s)

## Implementation notes

- Script: `importer/garminconnect/garmin_metrics.py` (`garminconnect==0.3.20`).
  - `login --token-dir DIR`: reads the email with `input`, the password with `getpass` and the MFA code with `input`; only `dump`s the tokens.
  - `serve --token-dir DIR --interval S`: a long-running process that logs in with tokens only (no account or password; exits 3 if the tokens are unusable). stdin carries one request per line, `<metric> <YYYY-MM-DD>`; stdout carries one line of raw JSON per request. Requests are at least S seconds apart. It exits on the first error without retrying, and writes the refreshed tokens back before exiting.
  - Exit codes: 0 success, 1 other, 3 tokens missing/expired/rejected, 4 rate limit (429) or CAPTCHA.
- Rust: `GarminConnectScript` in `src/garminconnect.rs` implements `MetricsSource`; `runsync login` hands the terminal straight to the script.
- Deviation: instead of extending `ActivitySource`, a sibling `MetricsSource` trait was added (sharing `SourceError`). Reason: the two sources make completely different requests, and ticket 05 was changing `ActivitySource` at the same time.
- Interval setting: `[sync] garminconnect_interval_s` in `config.toml`, default 5.0.
- Archive: `raw/garminconnect/<training_status|vo2max|race_predictor>/<YYYY-MM-DD>.json`; `rebuild` reads them back in.
- Table: `garmin_metrics` (migration `0005`), one row per day; each metric writes only its own columns.
- Sync: every run re-fetches the current day's three metrics and overwrites them; the backfill fetches every Sunday before today, newest to oldest, back to the week of the first activity; dates that already have a file are not requested again, so an interrupted run can resume. The result is recorded in `sync_runs` (source `garminconnect`). Without tokens, `sync` skips this source and suggests `runsync login`.

## Conclusion on historical queries

- At the library level, all three endpoints take a date parameter. `get_training_status(date)` → `/metrics-service/metrics/trainingstatus/aggregated/{date}`; `get_max_metrics(date)` → `/metrics-service/metrics/maxmet/daily/{date}/{date}`; `get_race_predictions(date, date, "daily")` → `/metrics-service/metrics/racepredictions/daily/{displayName}?fromCalendarDate&toCalendarDate`. So the weekly backfill is implemented.
- Real API: **unverified — needs user**. The development environment cannot read `secrets/garminconnect/` (permission denied), so no real request was sent.
- Field names follow the library's known response structure and were not checked against a real response: `mostRecentTrainingStatus.latestTrainingStatusData.<deviceId>.{trainingStatusFeedbackPhrase, primaryTrainingDevice, acuteTrainingLoadDTO.{dailyTrainingLoadAcute, dailyTrainingLoadChronic, dailyAcuteChronicWorkloadRatio}}`; `[].generic.{calendarDate, vo2MaxPreciseValue}`; `[].{calendarDate, time5K, time10K, timeHalfMarathon, timeMarathon}`.
- For the user to do: run `runsync sync` once and check whether the files for past Sundays under `raw/garminconnect/` have values. If past dates come back empty or the same as the current day, remove the backfill and keep only daily snapshots. If the field names differ, change `store_metric` in `garmin_metrics.rs` and run `runsync rebuild`.
