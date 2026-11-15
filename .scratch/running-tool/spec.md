# Personal running analysis tool: implementation spec

Label: ready-for-agent
Status: done

Source: the map [Personal running data analysis (Garmin)](../running-analysis/map.md) and the resolved tickets under it. The reasons and sources for each decision are given in each ticket's Answer; this spec only collects what to implement. Terms are in `GLOSSARY.md` at the root, product background in `PRODUCT.md`.

## Problem Statement

The user runs with a Garmin watch, and the account holds about 1000–1500 activities since 2021-08-06. The Training Load, VO2max and Race Predictor that Garmin Connect gives are black boxes: the formulas are not public, the parameters cannot be tuned, and they do not show "am I running faster at the same heart rate". Garmin's average pace also counts the walking time after a run, so the number is too slow. The user wants an analysis they compute themselves, in which every number can be traced back to a formula and parameters, to answer three questions:

1. Is recent training load enough, or too much?
2. Is aerobic fitness improving or declining over months to years?
3. Racing now, roughly what could I run at each distance?

The data is currently only at Garmin; the machine has no complete raw archive and no queryable analysis database.

## Solution

Two independent programs that exchange data only through the data directory:

- **Import CLI `runsync`** (Rust): syncs all of Garmin's history, and new data after that, to the machine. Raw files are stored as is in the raw archive, and parsed into the SQLite analysis database at the same time. Three commands, `sync`, `login` and `rebuild`, all run by hand.
- **Analysis package `running`** (Python): reads the analysis database only (it writes `state/` when pushing the 5K plan, see `deviations.md`), and computes aerobic fitness, training load, weekly volume and race predictions. The same computations serve Jupyter for deep exploration and the local dashboard. The dashboard is a FastAPI service running only on `127.0.0.1` plus static web pages; the user opens it once or twice a week and takes a few minutes to see "how should I train this week".

Whenever the user wants to see new data, they run `runsync sync` once and then open the dashboard.

## User Stories

**First-time setup**

1. As a runner, I want to point both programs at one data directory through `RUNNING_DATA_DIR`, so that my personal data never lives inside the repo or its worktrees.
2. As a runner, I want the data directory to default to `%USERPROFILE%\running-data` when the variable is unset, so that I don't have to configure anything on a fresh machine.
3. As a runner, I want my Personal API key read from a file under `secrets/` in the data directory, so that the key is never in the repo and never printed.
4. As a runner, I want to run `runsync login` once and type my Garmin password interactively, so that only a token is stored and the password never touches disk.
5. As a runner, I want `runsync login` to store the garminconnect token under `secrets/` in the data directory, so that all credentials live in one place I can protect.
6. As a runner, I want one `config.toml` holding physiology parameters, reference HR and request intervals, so that the importer and the analysis read the same settings.
7. As a runner, I want physiology parameters (HRmax, HRrest, LTHR) listed with an effective date, so that changing them later recalculates only activities after that date.
8. As a runner, I want a clear error when the data directory, config file or key file is missing, so that I know exactly what to create.

**Backfill and sync**

9. As a runner, I want the first `runsync sync` to backfill my full history since 2021-08 in one run, so that I don't have to babysit batches.
10. As a runner, I want a progress bar during backfill, so that I can tell the roughly 75-minute run is moving.
11. As a runner, I want backfill to resume from where it stopped when I rerun `sync` after an interruption, so that nothing is downloaded twice and no progress file can go stale.
12. As a runner, I want each downloaded file parsed into the analysis database right away, so that partial results are usable even if the run is interrupted.
13. As a runner, I want later runs of `sync` to fetch only new activities, so that an incremental sync takes seconds or minutes.
14. As a runner, I want activities from the last 7 days refetched on every sync, so that renames and type changes I make in Garmin Connect show up.
15. As a runner, I want daily summaries for the last 7 days refetched and upserted, so that today's incomplete data and Garmin's later corrections are picked up.
16. As a runner, I want all activity types synced, not only runs, so that strength and cycling sessions count toward training load without a second backfill.
17. As a runner, I want Garmin's Training Status, VO2max and Race Predictor backfilled one day per week and snapshotted on every sync, so that I can compare my numbers with Garmin's.
18. As a runner, I want requests sent one at a time with a fixed pause (1.5 s for Personal API, 5 s for garminconnect), so that I don't get rate-limited or locked out.
19. As a runner, I want a data source that returns 429 or `CAPTCHA_REQUIRED` to stop immediately without retrying, so that I don't make a lockout worse.
20. As a runner, I want a cooldown marker written after a 429, so that syncs in the next 24 hours skip that source and tell me why and until when.
21. As a runner, I want the two data sources to fail independently, so that a garminconnect problem never blocks my activities from syncing.
22. As a runner, I want `sync` to tell me to run `runsync login` when the garminconnect token has expired, so that I know the fix without reading logs.
23. As a runner, I want `sync` to tell me to generate a new Personal API key when the key is rejected, so that I can recover when it expires around 2027-10.
24. As a runner, I want `sync` never to prompt for a password, so that it can run unattended later if I add a scheduled task.
25. As a runner, I want log verbosity controlled by `RUST_LOG`, so that I can debug a failing sync without changing code.
26. As a runner, I want a sync to be safe while Jupyter or the dashboard has the database open, so that I don't have to close them first.

**Raw archive and rebuild**

27. As a runner, I want every FIT and JSON file stored exactly as Garmin returned it, so that the raw archive is the single source of truth.
28. As a runner, I want `runsync rebuild` to delete the analysis database and recreate it from the raw archive offline, so that parser fixes apply to all history without hitting Garmin.
29. As a runner, I want schema changes applied automatically by migrations at startup, so that upgrading the importer never requires a manual rebuild.
30. As a runner, I want a FIT file that fails to parse to be kept in the raw archive, logged and skipped, so that one bad file doesn't stop the whole sync or rebuild.
31. As a runner, I want to back up only the `raw/` directory, so that my backup stays small and everything else can be regenerated.

**Analysis (Jupyter)**

32. As a runner, I want every run's running pace computed from running seconds only, so that the walk after a run doesn't make it look slower.
33. As a runner, I want each second classified as running or walking by cadence, so that walk breaks in long runs are handled the same way.
34. As a runner, I want an aerobic value per run (GAP pace at reference HR 145 bpm, fitted on steady-state seconds), so that I can see whether I'm faster at the same effort.
35. As a runner, I want treadmill and trail runs excluded from the aerobic metric, so that unreliable pace and technical terrain don't distort the trend.
36. As a runner, I want runs with less than 10 minutes of steady state left out of the aerobic metric, so that intervals and short jogs don't add noise.
37. As a runner, I want hills corrected with Minetti's formula, so that hilly routes are comparable with flat ones.
38. As a runner, I want EF and decoupling for runs of 60 minutes or longer, so that I can judge my long-run durability.
39. As a runner, I want a TRIMP value for every activity with heart rate, so that all training counts toward load.
40. As a runner, I want activities without heart rate marked as missing load rather than estimated, so that gaps are visible.
41. As a runner, I want CTL (42 days), ATL (7 days) and TSB, so that I can see fitness, fatigue and freshness trends.
42. As a runner, I want weekly running distance by calendar week (Monday to Sunday, local time) plus a rolling 7 days, so that I can track volume both ways.
43. As a runner, I want to keep my races in a hand-maintained `races.csv`, so that only real all-out efforts drive predictions.
44. As a runner, I want 5K, 10K, half and full marathon predictions from VDOT, with Riegel and Garmin as comparisons, so that I can see how much the methods agree.
45. As a runner, I want the marathon prediction adjusted by my recent weekly distance, so that it doesn't overestimate me the way pure VDOT does.
46. As a runner, I want predictions marked stale when there is no race in the last 6 months, so that I'm not misled by old fitness.
47. As a runner, I want the same calculation functions available in Jupyter, so that what I explore there matches what the dashboard shows.
48. As a runner, I want notebook outputs stripped on commit, so that personal data never lands in git.

**Dashboard**

49. As a runner, I want the top of the dashboard to say whether my load this week is fine or spiking, so that I know what to do this week at a glance.
50. As a runner, I want a red headline when ATL/CTL exceeds 1.5, so that a load spike is impossible to miss.
51. As a runner, I want this week's and last week's distance next to a 12-week bar chart, with the unfinished current week greyed out, so that I can compare volume quickly.
52. As a runner, I want a prediction table with VDOT, Riegel and Garmin side by side and the basis stated underneath, so that I know which race it comes from.
53. As a runner, I want a full-width aerobic trend (weekly median dots, 4-week rolling line, race markers) with a weekly temperature chart below, so that I can read seasonal effects.
54. As a runner, I want to switch the aerobic trend between half a year, 1 year, 2 years and all, so that I can see both recent and long-term change.
55. As a runner, I want a crosshair readout of date, pace and temperature on hover, so that I can read exact values.
56. As a runner, I want weeks with fewer than 2 qualifying runs left blank on the chart, so that missing data isn't interpolated.
57. As a runner, I want tables of long runs (EF, decoupling above 5% in red) and recent races, so that I can review key sessions.
58. As a runner, I want a "how is this calculated" note beside each block, showing the formula and current parameters, so that every number explains itself.
59. As a runner, I want a red dot next to numbers that changed since my last visit and a "mark all as read" button, so that I can see what's new.
60. As a runner, I want an empty state with the `runsync sync` / `runsync login` steps and the data directory when nothing has been synced, so that first use isn't a blank page.
61. As a runner, I want the dashboard reachable only from my own machine, so that my health data is never exposed to the network.
62. As a runner, I want the dashboard to work offline with self-hosted fonts, so that no request leaves my machine.
63. As a runner, I want interface text in Chinese with CTL, ATL, TSB, VDOT, EF and TRIMP kept in English, so that the terms match what I read elsewhere.

## Implementation Decisions

**Overall structure**

- Two independent projects at the repository root: a Rust crate (binary `runsync`) and a uv-managed Python project (package `running`); no Cargo workspace and no uv workspace. The dashboard is part of the Python project.
- The two sides exchange data only through the data directory; the one exception is `running-push-plan --apply`, which calls the importer's garminconnect script to push the 5K plan (see `deviations.md`). The analysis database schema is owned by Rust; Python always opens it read-only.
- The data directory is set by `RUNNING_DATA_DIR`, defaulting to `%USERPROFILE%\running-data`. Layout: `config.toml`, `races.csv`, `secrets/` (Personal API key, garminconnect token), `raw/` (raw archive), `state/` (cooldown markers; plus `plan5k_push.json`, recording the ids of plan workouts pushed to Garmin), `running.sqlite` (analysis database), and an optional `analysis.sqlite` (Python's cache of derived values).
- `config.toml` is shared by both sides; Rust reads it with the `toml` crate, Python with `tomllib`. Its shape (from the ticket "Project skeleton and dependencies"):

```toml
[aerobic]
reference_hr = 145

[[physiology]]
effective_from = 2021-08-01
hr_max = 192
hr_rest = 55
lthr = 170
```

  The other thresholds (cadence 140 spm, the steady-state segment conditions, request intervals) also go into the config, with defaults in code.

**Import CLI `runsync`**

- Dependencies: `reqwest` (`blocking`, `json`, `rustls-tls`, no tokio), `rusqlite` (bundled), `fitparser`, `clap` (derive), `anyhow`, `log` + `env_logger`, `indicatif`, `serde`, `serde_json`, `toml`, `zip`, `chrono`. Toolchain: rustup stable, `x86_64-pc-windows-msvc`, edition 2024.
- **Data source trait**: a data source is abstracted as a trait with two implementations, the Personal API client and the small garminconnect script. The sync logic depends only on this trait (the test seam, see below). Errors fall into three kinds, represented by a small enum: rate-limited (429 or `CAPTCHA_REQUIRED`), invalid credentials, other.
- **Personal API client**: hand-written with `reqwest` + `serde`, implementing only the GET endpoints in use: activity list paging, activity details, FIT download (a zip; extract the single FIT inside and discard the zip), daily summaries (one 7-day range per request). Each `sync` run exchanges the key for an access token once (`POST` to the personal-api-key token endpoint with the header `Authorization: ApiKey <key>`; the response is a plain-text JWT, whose expiry is taken from `exp`), and exchanges again when close to expiry. The token is not written to disk.
- **Small garminconnect script**: a PEP 723 Python script kept in the Rust project, depending on `garminconnect`, called by the CLI with `uv run --script`, its path fixed at compile time by `CARGO_MANIFEST_DIR`. Subcommands: `login` (reads the password with `getpass` and saves only the token) and queries for the three metrics. stdout outputs only JSON; exit codes distinguish success, rate-limited, authentication failure and other errors. Garmin login is not rewritten in Rust.
- **Raw archive layout**: Personal API `activities/<activityId>.fit` and `activities/<activityId>.json`, `daily_summaries/<YYYY-MM-DD>.json`; garminconnect `<metric>/<YYYY-MM-DD>.json`; the account data export package is kept as is in `export/<export date>/` and parsed by `runsync import-export` (see ticket 17). Re-fetched data overwrites the file of the same name; no history of versions is kept. Empty HRV and sleep responses stay only in the raw archive, with no tables.
- **Sync algorithm**:
  - New activities: page through the activity list from newest to oldest until every activity on a page is already in the raw archive.
  - Activities within the last 7 days: re-fetch the detail JSON and overwrite it; download the FIT only when missing.
  - Daily summaries: re-fetch the last 7 days on every run, overwrite and upsert.
  - The three Garmin metrics: during backfill take one day per week; after that store a snapshot of the current day on every sync. Whether the endpoints can query history by date is to be verified during implementation; if not, only snapshots are stored.
  - Resuming depends only on whether the raw file already exists; no progress is stored. Each downloaded file is parsed and written to the database at once.
  - The two data sources are processed serially and independently: an error in one does not affect the other.
  - Rate limiting: stop that data source at once and write a cooldown marker (with time and reason) in `state/`. Within 24 hours it is skipped, with the reason stated. Invalid credentials: stop that data source and prompt to run `login` (garminconnect) or generate a new key (Personal API).
- **Migrations**: hand-written SQL files compiled into the binary with `include_str!`, versioned with `PRAGMA user_version`; at startup, the files not yet run are executed in order within one transaction. No `rusqlite_migration`. The analysis database uses WAL.
- **`rebuild`**: delete the analysis database, recreate it from the schema, and re-parse the whole raw archive. Fully offline.
- **FIT parsing**: `fitparser`. Known issue #58: a whole file fails to parse when a developer field appears before its description. Such files are logged and skipped, with `rustyfit` as the fallback. Private messages (`unknown_*`) are not stored.

**Analysis database schema** (units always SI: m, m/s, s, bpm; timestamps in UTC)

- `activities`: one row per activity. Typed columns picked from the detail JSON: activity_id, type, `start_time_utc`, `start_time_local`, distance, duration, average and maximum heart rate, ascent and so on. The full JSON stays only in the raw archive.
- `records`: a long table of per-second data streams, primary key `(activity_id, timestamp)`, with columns `heart_rate`, `speed`, `cadence`, `altitude`, `distance`, `lat`, `lon`, `power`, `temperature`, NULL when missing. `cadence` is stored as in the FIT, as single-foot cadence.
- `laps`: the watch's laps.
- `daily_wellness`: one row per day (resting heart rate and so on), upserted.
- `garmin_metrics`: one row per day, storing snapshots of the three Garmin metrics.

**Analysis package `running`**

- Python 3.14, depending on polars and DuckDB (`ATTACH` SQLite, read-only), with no direct pandas dependency. jupyterlab goes in the dev dependency group. `nbstripout` clears notebook outputs on commit. Derived values are computed fresh each time and not stored; if caching is needed later, they go into `analysis.sqlite`.
- Modules are split by domain: config and data reading; run/walk classification and running pace; aerobic fitness; training load; weekly volume; race prediction. Notebooks and the dashboard call only the public functions of these modules.
- **Running and walking**: cadence ×2 gives spm, smoothed over 10 seconds; ≥140 spm counts as running; walking stretches shorter than 10 seconds still count as running. Running pace = distance of running seconds ÷ duration of running seconds. Garmin's average pace is kept as a reference.
- **Aerobic fitness**: only outdoor road runs count (`running` type, excluding treadmill and trail). Steady-state segment: drop the first 10 minutes; smooth heart rate and speed each with a 30-second rolling window; keep only seconds that satisfy all of: running, heart rate within ±15 bpm of the reference heart rate, speed change ≤5% within 60 seconds, no pause, and a difference between heart rate and spm of ≥5. Runs with less than 10 minutes of valid time do not count. Grade is computed from smoothed barometric altitude over a 30-second distance window, clamped to ±15%, and Minetti 2002's `Cr(i)` converts speed to GAP speed. A line `GAP speed ~ heart rate` is fitted on the steady-state seconds, and its value at the reference heart rate is the run's aerobic fitness value. Weekly, take the median of valid runs, leave weeks with fewer than 2 empty, then compute a 4-week rolling median. Temperature is the watch temperature from the FIT, averaged by week for display only, with no correction.
- **EF and decoupling**: EF = GAP speed ÷ heart rate, using only steady-state segments; the steady-state segment does not apply aerobic fitness's heart-rate band (145 ± 15), since otherwise seconds that drift out of the band would be dropped and decoupling could not show the drift. Decoupling is computed only for runs ≥60 minutes, and >5% is flagged.
- **Training load**: per-second Banister TRIMP, male coefficient `0.64·e^(1.92x)`, `x = (HR − HRrest) / (HRmax − HRrest)`, with the parameter set in effect on the activity's date. Every activity with heart rate counts; those without heart rate are recorded as missing. CTL is a 42-day EWMA, ATL 7 days, TSB = CTL − ATL. ATL/CTL > 1.5 is flagged as "负荷突增" (load spike).
- **Weekly volume**: counts only running activities (road, treadmill and trail all count), and only the distance of running seconds. Grouped by calendar week (Monday to Sunday) of `start_time_local`, with a rolling 7-day value as well.
- **Race list**: `races.csv`, fields `date, activity_id, distance_m, time_s, all_out, note`. A clear message is given when it is missing or malformed.
- **Race prediction** (5K, 10K, half, marathon): compute VDOT from the best `all_out` race within the last 6 months, then convert to each distance. Riegel as comparison: with 2 or more races fit a personal exponent, otherwise use 1.06. The marathon is adjusted by the average weekly volume of the last 8 weeks, following Vickers 2016. Garmin Race Predictor's value as reference. Without a race within 6 months, mark it stale and give no prediction.

**Dashboard**

- FastAPI binds only to `127.0.0.1`, with no accounts. It does one thing: call `running` to compute and return JSON. The same service serves the static frontend files.
- The JSON API is split by dashboard block: load (current CTL/ATL/TSB and the last 12 weeks' series, the spike flag), weekly volume (this week, last week, rolling 7 days, last 12 weeks), race prediction (three methods, basis, whether stale), aerobic fitness trend (weekly series by range parameter, including empty weeks and weekly temperature), the long-run table, recent races, data status (whether synced, last sync time, data directory). Exact paths and field names are fixed during implementation and form the Seam 3 contract.
- Each block's response carries the formula name and current parameters needed for "how is this calculated"; the frontend only displays them.
- Frontend: native ES modules + hand-written SVG charts, no node build, no chart library. Fonts (Noto Serif SC, Noto Sans SC, IBM Plex Sans) are self-hosted. The "changed since last visit" red dot records the last seen values in browser localStorage; the server writes nothing.
- Visuals and layout follow variant A of the HTML prototype on the prototype branch `prototype/dashboard` (commit `8013fab`): newspaper sports-section style, newsprint background `#f3efe6`, ink-black text, red `#b0281f` used only for annotations and warnings; numbers use tabular-nums; at most 2 editorial annotations per chart. The aerobic fitness chart uses the crosshair readout of prototype variant C. The prototype uses synthetic data; the production version switches to API data.
- Three states: not synced (empty state, showing the sync steps and the data directory), prediction stale (the prediction table fades, red text gives the date of the latest race and suggests updating `races.csv`), weeks with too little data (the point stays empty, no interpolation).

## Testing Decisions

A good test checks results only through external behaviour: given inputs (fixture files, a synthetic database, a fake data source), check outputs (database contents, file system state, command output, JSON), not how internal functions are called or what intermediate structures look like. The test seams are only the ones below; no new abstraction layers are added just for testing.

- **Seam 1: import CLI, raw archive to analysis database.** Prepare a small raw archive fixture directory (hand-written detail JSON, daily summary JSON, and small synthetic FIT files), run `rebuild` on it, then query the resulting SQLite directly, asserting: row counts per table; SI units; correct `start_time_utc` and `start_time_local`; repeated writes for the same day are upserts; unparseable FIT files are skipped rather than aborting; migrations run to the latest version on both an empty database and an older database. The fixtures contain no real GPS and can be committed. Integration tests reading real FIT files read from the data directory, are marked `#[ignore]`, and are run by hand with `cargo test -- --ignored`.
- **Seam 2: import CLI, `sync` against the data source trait.** Drive `sync` with in-memory fake data sources, asserting the results in the raw archive and `state/`: skip when the raw file already exists (resume); paging stops when a whole page already exists; details and daily summaries of the last 7 days are overwritten; after a data source returns rate limiting a cooldown marker is written, a rerun within 24 hours skips that data source, and after 24 hours it resumes; when one data source fails the other completes as usual; invalid credentials print the matching message. Real HTTP is not tested, and the real Python script is not called.
  - **Exception (ticket 22a)**: one test in `importer/tests/open_meteo.rs` starts a stub server with a local `TcpListener` (`127.0.0.1`, returning a fixed status code) and a closed port, and drives the real `OpenMeteoClient`. Reason: what needs proving is that the real client's error messages contain neither the grid point coordinates nor the request URL (reqwest errors include the URL by default, and the URL contains coordinates), which a fake data source cannot test. Connections go only to the local machine; there is no external network access and no real request to Open-Meteo. The other Open-Meteo tests use in-memory fake data sources as usual.
- **Seam 3: dashboard JSON API.** pytest + FastAPI `TestClient`; at test startup, generate a small `running.sqlite` from synthetic data (with the same schema as Rust), plus `config.toml` and `races.csv`. Assert the values each endpoint returns, and three states: no analysis database or an empty one; no race within 6 months; a week with fewer than 2 valid runs.
- **Formula-level tests (the only addition beyond Seam 3)**: the formulas TRIMP, VDOT conversion, Riegel, the Vickers adjustment and Minetti `Cr(i)` are tested with pytest directly on `running`'s public functions, checked against values from the original sources. All other logic (steady-state filtering, run/walk classification, weekly aggregation, EWMA) is tested through Seam 3.
- The repository has no code yet, so there are no existing tests to follow.
- Formatting and lint: Rust uses `rustfmt` + `clippy`, Python uses `ruff`. No pre-commit hook and no `justfile`; common commands go in the README.

## Out of Scope

- Data quality and cleaning (optical heart-rate artefacts, GPS drift, pauses and auto-pause, treadmill activity issues): after the first backfill, count the actual situation in Jupyter, then decide in separate tickets.
- Temperature correction: the first version only shows weekly mean temperature. Whether to regress against external historical air temperature (which sends a location to a third party) is decided after looking at the seasonal swing across the whole history.
- Fitting the full Banister performance model; using ACWR as an injury warning.
- Parsing anything in the account data export package other than activities, FIT, daily summaries and the three Garmin metrics (sleep, profile and so on): it is only archived as part of the whole package (ticket 17).
- HRV and sleep analysis: the user does not wear the watch at night, so there is no data.
- Scheduled automatic sync (Windows Task Scheduler).
- Multiple users, accounts, cloud deployment, phone access.
- Tauri or any other desktop shell; Streamlit.
- Garmin Connect Developer Program.

## Further Notes

- **Confirmed deviations**: five places where the implementation differs from this spec and the user confirmed on 2026-10-31 to keep them (9 running types, TSB using the previous day's CTL/ATL, Riegel k clamped to [1.01, 1.20], a separate `MetricsSource`, exit code 0 when skipped for cooldown), plus training status unified without a numeric suffix; see [deviations.md](deviations.md).

- **Implementation prerequisites**: the machine has no Rust yet. First install rustup, and Visual Studio Build Tools with the C++ workload (the bundled feature of `rusqlite` uses it to compile SQLite).
- **Credentials**: the user moves `.env` from the repository root into the data directory's `secrets/` themselves, and moves the `garminconnect` token from `~/.garminconnect` there. During implementation, never read, print or commit the content of any key or token. The Personal API key expires around 2027-10.
- **Login risk**: the garminconnect mobile login strategy on this machine has already received a 429 and must fall back to the backup strategy. Reuse the token as much as possible and log in rarely; do not call `login` repeatedly while debugging.
- **Formula sources**: the original texts of the VDOT table, the Vickers 2016 coefficients and the Banister TRIMP coefficients were not read during research; check the original sources before writing code (see the ticket "Survey of methods for aerobic fitness, training load and race prediction" and the branch `research/analysis-methods`).
- **To verify during implementation**: whether the three garminconnect metrics can query history by date; whether `fitparser` and `rustyfit` build on Windows; whether the reference heart rate of 145 is close to the median easy-run heart rate in real data, adjusting once if clearly off.
- **Account data export**: the export package arrived (2026-10); `runsync import-export <zip>` stores it in `raw/export/<export date>/` and parses it, replacing most of the API backfill (ticket 17).
- Research material is on the branches `research/garmin-data-access`, `research/analysis-methods` and `research/rust-api-coverage`, and the prototype on `prototype/dashboard`; none are merged into main.
