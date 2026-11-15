# 02: Tracer bullet: from the raw archive to the empty dashboard

**What to build:** The narrowest path through the whole chain. The import CLI rebuilds the activity detail JSON in the raw archive into the analysis database; the analysis package opens the analysis database read-only; the local dashboard shows one of two states: an empty "no data yet" state (listing the steps for `runsync sync` and `runsync login`, and where the data directory is), or "N activities, last synced at …". This ticket sets up the skeleton of both projects; later tickets add features on top.

**Blocked by:** 01 (prerequisites: toolchain and credentials in place)

**Status:** done

Source: User Stories 1, 2, 6, 8, 27–29, 31, 48, 60–63 in the [implementation spec](../spec.md).

- [x] The repository root holds two independent projects: a Rust crate (binary `runsync`) and a uv-managed Python project (package `running`, Python 3.14), with no workspace of any kind
- [x] Both find the data directory through `RUNNING_DATA_DIR`, default `%USERPROFILE%\running-data`, and both read the same `config.toml`; a missing file gives a clear error
- [x] Migrations are hand-written SQL compiled into the binary, versioned with `PRAGMA user_version`, and run in one transaction at startup; the analysis database uses WAL
- [x] `runsync rebuild` deletes the analysis database and rebuilds the `activities` table from the raw archive (type, `start_time_utc`, `start_time_local`, distance, duration, heart rate, elevation gain and so on, in SI units), fully offline
- [x] The `runsync sync` and `runsync login` subcommands exist and for now only say "not implemented yet"
- [x] The analysis package attaches the analysis database read-only through DuckDB `ATTACH` and returns data as polars, with no pandas dependency
- [x] FastAPI binds only to `127.0.0.1`, serves a "data status" endpoint, and hosts the static frontend
- [x] The frontend is plain ES modules with no node build; fonts (Noto Serif SC, Noto Sans SC, IBM Plex Sans) are hosted locally; the visual tone follows prototype variant A (newsprint background `#f3efe6`, ink-black text); the interface text is Chinese
- [x] Seam 1 tests: run `rebuild` on a hand-written raw archive fixture and query SQLite to assert row counts, units and both timestamps; migrations bring both an empty database and an older-version database up to the latest
- [x] Seam 3 tests: `TestClient` with a synthetic analysis database covers the "no analysis database or an empty one" and "has data" responses
- [x] `.gitignore` covers Rust's target directory and Python's `.venv`; `nbstripout` is set up; `rustfmt`, `clippy` and `ruff` all pass
- [x] The README lists the common commands: build, `rebuild`, start the dashboard, run both test suites
