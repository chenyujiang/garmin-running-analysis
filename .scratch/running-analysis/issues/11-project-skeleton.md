# Project skeleton and dependencies

Type: grilling
Status: resolved
Blocked by: none

## Question

How are the Rust import CLI and the Python analysis code organised in the same repository, and which dependencies does each use?

- Directory layout: where the Rust crate and the Python project (`uv`) live; where the PEP 723 script for the three `garminconnect` metrics lives.
- Rust dependencies: `reqwest`, `serde`, `rusqlite` (bundled), `fitparser`, plus how SQLite migrations are managed (hand-written SQL files or a crate like `rusqlite_migration`), CLI argument parsing, logging.
- Python dependencies: Python version, polars or pandas as the DataFrame library, how Jupyter plugs into the `uv` project, whether DuckDB reads the analysis database.
- Config: data directory path, location of the API key, and how Rust and Python both read the same config (see [Storage design](04-storage.md): the data directory is outside the repository, set by config or an environment variable).
- The dashboard stack is not decided here; see [Dashboard design](08-dashboard-design.md).

## Comments

- 2026-10-23 (from [Backfill and incremental sync strategy](05-sync-strategy.md)): the import CLI has three commands, `sync`, `login` and `rebuild`; `login` calls garminconnect's small Python script and reads the password interactively. Besides `raw/`, the data directory has `state/` for cooldown markers.
- 2026-10-23 (from [Training load model and race prediction method](07-load-and-prediction.md)): the physiological parameters (HRmax, HRrest, LTHR) are configured by effective date, and the reference heart rate is in the config too; `races.csv` is maintained by hand by the user and lives in the data directory. Where these config files live and in what format is decided here.

## Answer

Decided point by point with the user on 2026-10-23.

**Directory layout**: two independent projects in the repository root, with neither a Cargo workspace nor a uv workspace.

```
importer/                     Rust crate, binary name runsync
  src/
  migrations/                 0001_init.sql …
  scripts/garmin_metrics.py   PEP 723 script: three Garmin metrics + login
analysis/                     uv project
  src/running/                aerobic.py, load.py, predict.py …
  notebooks/
  tests/
GLOSSARY.md
.scratch/                     maps and trial-pull scripts, kept as is
```

- At compile time the CLI gets the absolute path of `scripts/garmin_metrics.py` from `CARGO_MANIFEST_DIR` and calls it with `uv run --script`. For a single user running locally, that is enough.
- Commands: `runsync sync`, `runsync login`, `runsync rebuild`.
- `.gitignore` gains `importer/target/` and `analysis/.venv/`.

**Rust**:

- Toolchain: rustup stable, `x86_64-pc-windows-msvc`, edition 2024.
- HTTP: `reqwest` with the `blocking`, `json` and `rustls-tls` features, no tokio. All requests are serial, so async is not needed; rustls does not depend on the system OpenSSL.
- Migrations: hand-written. `migrations/NNNN_*.sql` are compiled into the binary with `include_str!`; `PRAGMA user_version` records the version, and on startup the files not yet run are executed in order within one transaction. No `rusqlite_migration`, because its version is tied to `rusqlite` and both would have to change together on upgrade.
- Error handling: `anyhow`, plus a small enum distinguishing "data source rate-limited (429/CAPTCHA)", "credentials invalid" and "other error". `sync` uses it to decide whether to stop that source and write a cooldown marker, or to suggest running `login`.
- Other dependencies: `clap` (derive), `log` + `env_logger` (level controlled by `RUST_LOG`), `indicatif` (backfill progress bar), `serde`, `serde_json`, `toml`, `zip`, `chrono`, `fitparser`, `rusqlite` (bundled).

**Python**:

- `analysis/` is pinned to 3.14 with `.python-version`. The PEP 723 script declares `requires-python = ">=3.12"` and depends on `garminconnect`; uv manages its environment.
- polars is the workhorse. The analysis database is read with DuckDB (`ATTACH` the SQLite file), always opened read-only. No direct dependency on pandas.
- `jupyterlab` goes into uv's dev dependency group and is started with `uv run jupyter lab`; in VS Code, pick `analysis/.venv` as the kernel.
- The computation lives in the `analysis/src/running/` package; notebooks only call it and plot, and the dashboard later reuses the same code.
- `nbstripout` clears notebook outputs on commit, because the outputs contain personal data.

**Data directory and config**: the data directory is set by the environment variable `RUNNING_DATA_DIR`, default `%USERPROFILE%\running-data`. Personal data and config all live here; the repository holds only code.

```
running-data/
  config.toml          physiological parameters (by effective date), reference heart rate, request intervals
  races.csv            race list maintained by hand
  secrets/
    personal_api.key   bare key, same format as the current .env
    garminconnect/     garminconnect tokens, moved from ~/.garminconnect
  raw/                 raw archive, the only part that needs backing up
  state/               cooldown markers
  running.sqlite       analysis database, written by Rust
  analysis.sqlite      cache of derived values, owned by Python, optional
```

- Rust reads `config.toml` with the `toml` crate and Python with the standard library's `tomllib`; both read the same file. Example:

```toml
[aerobic]
reference_hr = 145

[[physiology]]
effective_from = 2021-08-01
hr_max = 192
hr_rest = 55
lthr = 170
```

- The user moves the `.env` in the repository root to `secrets/personal_api.key` themselves. That way the key does not appear in any worktree and does not go into backups.

**Tests**: real FIT files carry GPS tracks and stay out of git.

- Rust: unit tests for JSON parsing and migrations use small hand-written fixtures committed to the repository. Integration tests for FIT parsing read real files from the data directory, are marked `#[ignore]`, and are run by hand with `cargo test -- --ignored`.
- Python: pytest, testing TRIMP, steady-state segments, VDOT and other calculations with synthetic polars DataFrames.

**Formatting and lint**: `rustfmt` + `clippy` for Rust, `ruff` for Python. No pre-commit hook and no `justfile`; common commands go in the README.

**Prerequisites for implementation** (no ticket; implementation is outside this map): there is no Rust on this machine yet. First install rustup and Visual Studio Build Tools with the C++ workload (`rusqlite`'s bundled feature uses it to compile SQLite).
