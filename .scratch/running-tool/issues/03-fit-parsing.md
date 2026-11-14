# 03: FIT parsing into `records` and `laps`

**What to build:** `runsync rebuild` parses the FIT files in the raw archive and writes the per-second data streams and laps into the analysis database, so later analysis has data to work with. A file that fails to parse is only logged and skipped; it does not stop the whole rebuild.

**Blocked by:** 02 (tracer bullet: from the raw archive to the empty dashboard)

**Status:** done

Source: User Story 30, and "FIT parsing" and "Analysis database schema" under Implementation Decisions, in the [implementation spec](../spec.md).

- [x] Parse FIT with `fitparser`; first confirm it builds on Windows, and if it does not, switch to `rustyfit` and record why in this ticket
- [x] The `records` table has primary key `(activity_id, timestamp)` and columns `heart_rate`, `speed`, `cadence`, `altitude`, `distance`, `lat`, `lon`, `power`, `temperature`, NULL when missing; SI units, UTC timestamps; `cadence` is stored as in the FIT, single-foot cadence
- [x] The `laps` table stores the watch's laps
- [x] Private messages (`unknown_*`) are not stored
- [x] A FIT that cannot be parsed (including the `fitparser` issue #58 kind) stays in the raw archive, gets one log line, and is skipped
- [x] Seam 1 tests: the fixtures hold a few small synthetic FIT files (no real GPS) plus one broken file; assert the row counts and units of `records` and `laps`, and that the broken file is skipped instead of stopping the run
- [x] The integration test that reads real FIT files reads them from the data directory, is marked `#[ignore]`, and is run by hand with `cargo test -- --ignored`

## Outcome

- **Parser**: `fitparser` 0.11.0 builds as is on Windows (`x86_64-pc-windows-msvc`, rustup stable); no switch to `rustyfit`.
- **Issue #58**: still present in 0.11.0. The synthetic test file (a definition message declares developer fields without a preceding `developer_data_id`/`field_description`) makes the whole file fail to parse, so it is handled as "log and skip".
- **Schema**: migration `0003_records_laps.sql`.
  - `records`: `timestamp` is ISO UTC with a `Z`; `lat`/`lon` are converted from semicircles to degrees; `speed` and `altitude` prefer `enhanced_*` and fall back to the plain fields; `cadence` is single-foot cadence (multiply by 2 for spm). Record messages without a timestamp are dropped; when one second repeats, the later message overwrites the earlier.
  - `laps`: primary key `(activity_id, lap_index)`, with `lap_index` counting from 0 in file order. Columns: `start_time_utc`, `end_time_utc`, `elapsed_duration_s`, `timer_duration_s`, `distance_m`, `avg_speed_mps`, `max_speed_mps`, `avg_hr_bpm`, `max_hr_bpm`, `avg_cadence`, `max_cadence` (single foot), `avg_power_w`, `elevation_gain_m`, `elevation_loss_m`.
  - Neither table has a foreign key to `activities`: an activity with a FIT but no detail JSON can still be stored.
- **Only `record` and `lap` messages are read**, decoded with `DropUnknownMessages`, so neither private messages nor other messages are stored.
- **Synthetic FIT**: generated on the fly in tests by a small FIT encoder in `importer/tests/common/fit.rs`; there are no binary fixtures in the repository.
- **Real FIT test**: `importer/tests/real_fit.rs` only parses, does not rebuild, never touches the real analysis database, and prints only counts. At implementation time the data directory had no FIT files yet (`sync` was not implemented), so this test had not yet run on real data.
- The `rebuild` output becomes `rebuilt <path>: N activities, M FIT files, K files skipped`, where `skipped` counts both JSON and FIT files.
