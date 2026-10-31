# garmin-running-analysis

A personal running analysis tool for one Garmin account. It pulls the full activity history (per-second FIT data, daily summaries, and a few Garmin metrics) into a local archive, then computes its own transparent, tunable metrics instead of relying on Garmin's black-box numbers:

- **Aerobic fitness trend**: grade-adjusted pace at a fixed reference heart rate, fitted on steady-state seconds of each run, shown as weekly medians with a 4-week rolling median.
- **Training load**: Banister TRIMP per activity, CTL/ATL/TSB trends, and a load-spike warning.
- **Weekly volume**: running distance per week (walking seconds left out), with running pace.
- **Long runs**: efficiency factor and aerobic decoupling for runs of an hour or more.
- **Race prediction**: VDOT from recent all-out races, with Riegel and Garmin's Race Predictor for comparison.

Every number links back to a documented formula and configurable parameters. Garmin's own figures appear only as a reference.

## Status

All commands work: `runsync sync` pulls activities and daily summaries from the Personal API and a few metrics from garminconnect, `runsync login` stores a garminconnect token, `runsync import-export` loads Garmin's account data export, and `runsync rebuild` rebuilds the analysis database from the raw archive. The dashboard shows weekly volume, training load, the aerobic trend, long runs and race predictions. Tickets live in `.scratch/running-tool/issues/`; deviations from the spec that still need a decision are listed in `.scratch/running-tool/deviations.md`.

| Path | Contents |
|---|---|
| `importer/` | Rust crate, binary `runsync` |
| `analysis/` | uv-managed Python 3.14 project, package `running` (analysis code and dashboard) |
| `.scratch/running-analysis/map.md` | Decision map: every design question and how it was resolved |
| `.scratch/running-analysis/issues/` | One file per decision (data access, analysis methods, storage, sync, metrics, dashboard design) |
| `.scratch/running-tool/spec.md` | Implementation spec: user stories, architecture, schema, testing seams |
| `.scratch/running-tool/issues/` | The spec broken into 17 vertical-slice tickets |
| `GLOSSARY.md`, `PRODUCT.md` | Domain vocabulary and product context |

Supporting material lives on branches that are never merged:

- `research/garmin-data-access`, `research/analysis-methods`, `research/rust-api-coverage`: research reports
- `prototype/dashboard`: throwaway dashboard prototypes (a static HTML version and a Streamlit comparison), using synthetic data

Most documents are written in Chinese.

## Architecture

- **Rust CLI (`runsync`)**: syncs from the official Garmin Connect Personal API, stores raw FIT and JSON files unchanged in a data directory outside the repository, and builds a SQLite analysis database from them.
- **Python analysis package**: polars and DuckDB over the read-only analysis database; also usable from Jupyter.
- **Dashboard**: FastAPI bound to `127.0.0.1`, serving JSON to a static frontend (plain HTML, native ES modules, hand-written SVG charts).

## Data directory

Both projects find their data through `RUNNING_DATA_DIR`, defaulting to `%USERPROFILE%unning-data`. It holds `config.toml`, the hand-kept `races.csv`, the raw archive (`raw/`), credentials (`secrets/`), cooldown markers (`state/`) and the analysis database `running.sqlite`.

`config.toml` (only `[[physiology]]` is required; every other key shows its default):

```toml
[[physiology]]                  # one block per change; each activity uses the set in effect on its date
effective_from = 2021-08-01
hr_max = 192
hr_rest = 55
lthr = 170

[aerobic]
reference_hr = 145              # GAP pace is read off at this heart rate
warmup_s = 600                  # moving time dropped at the start of each run
smoothing_s = 30                # trailing mean for HR, speed and altitude
hr_band_bpm = 15                # steady seconds: smoothed HR within reference_hr +- this
speed_window_s = 60
max_speed_change = 0.05         # (max - min) / mean of smoothed speed in that window
min_hr_spm_gap = 5              # |HR - spm| below this looks like cadence lock
min_steady_s = 600              # runs with less steady time are left out
grade_window_s = 30
max_grade = 0.15
min_runs_per_week = 2
rolling_weeks = 4
max_speed_mps = 7.0             # per-second speed above this is suspect (GPS drift)
max_fast_s = 60                 # runs with more seconds above max_speed_mps are left out

[run_walk]
cadence_spm = 140               # smoothed cadence (both feet) at or above this is running
smoothing_s = 10
min_walk_s = 10                 # shorter walking stretches still count as running
pause_gap_s = 10                # a longer gap between samples is a pause

[load]
max_sample_gap_s = 10           # a longer gap between HR samples counts only this long in TRIMP

[sync]
personal_api_interval_s = 1.5   # pause between Personal API requests
garminconnect_interval_s = 5.0  # pause between garminconnect requests
```

`races.csv` lists your races by hand, UTF-8 (saving from Excel with a BOM is fine). First line and an example:

```csv
date,activity_id,distance_m,time_s,all_out,note
2026-04-12,21234567890,21097.5,5880,yes,city half marathon
```

`activity_id` may be empty; `all_out` is `yes` or `no` (also `true`/`false`, `1`/`0`, `y`/`n`, `是`/`否`). Only all-out races from the last 6 months drive the predictions. The dashboard says when the file is missing or malformed.

`runsync sync` reads the Personal API key from `secrets/personal_api.key` (the bare key on one line; generate it at https://connect.garmin.com/app/settings/personalApiToken). It downloads every activity's detail JSON and FIT into `raw/personal_api/activities/` and daily summaries into `raw/personal_api/daily_summaries/`, loading each file into `running.sqlite` straight away. Rerun it after an interruption to resume. Later runs fetch only new activities and refetch details from the last 7 days. It then fetches garminconnect metrics (race predictor and others) into `raw/garminconnect/` if `runsync login` has stored a token in `secrets/garminconnect/`; without a token that source is skipped. A source that is rate limited stops at once and is skipped for 24 hours (marker in `state/`, delete it to retry sooner); a rejected key or token ends with how to replace it.

### Importing the Garmin account export

The full history can come from Garmin's account data export instead of thousands of API requests:

1. Request the export in your Garmin account (Account > Data Management > Export Your Data) and download the zip from the e-mail Garmin sends.
2. Run `runsync import-export <path to the zip>`. It copies the zip unchanged to `raw/export/<export date>/` (the newest modification date inside the package), then loads activities, activity FIT files, daily summaries and Garmin's VO2max, race predictor and training status from that copy into `running.sqlite`. It prints counts and date ranges, including FIT files skipped because they are not activities (daily monitoring and the like). Importing the same zip again changes nothing; a newer export overrides an older one. Data already downloaded from the APIs takes precedence over the export. Sleep, profile and the rest of the package are archived but not parsed.
3. Run `runsync sync` as usual. Activities and days the export already holds are not requested again, so only data after the export date (plus the usual 7-day refresh and today's Garmin metrics) is fetched.

`runsync rebuild` loads the archived exports again. The export contains GPS tracks and your e-mail address: keep it in the data directory, never in the repository.

## Common commands

Importer (run in `importer/`):

```sh
cargo build --release          # binary at target/release/runsync.exe
cargo run -- sync              # fetch new data from the Personal API and garminconnect (RUST_LOG=debug for detail)
cargo run -- login             # log in to garminconnect once and store the token (interactive)
cargo run -- import-export <zip>   # archive and load a Garmin account export, offline
cargo run -- rebuild           # delete running.sqlite and rebuild it from raw/, offline
cargo test
cargo fmt
cargo clippy --all-targets -- -D warnings
```

Analysis and dashboard (run in `analysis/`):

```sh
uv sync
uv run python scripts/fetch_fonts.py   # once: download the self-hosted fonts (not committed)
uv run running-dashboard               # http://127.0.0.1:8765
uv run pytest
uv run ruff format
uv run ruff check
```

Tests never touch the real data directory; they build temporary ones and point `RUNNING_DATA_DIR` at them.

## Notebooks

`analysis/notebooks/explore.ipynb` is the starting point for exploring your data. It calls the same public functions as the dashboard (weekly volume, training load, aerobic trend, per-run tables, per-second steady-state data), so its numbers match the dashboard.

Start JupyterLab (it is in the `dev` dependency group, which `uv sync` installs):

```sh
cd analysis
uv sync
uv run jupyter lab notebooks/explore.ipynb
```

The notebook reads `RUNNING_DATA_DIR` (default `%USERPROFILE%\running-data`); set it before starting Jupyter to point at another data directory.

In VS Code: run `uv sync` in `analysis/` first, open the notebook, click **Select Kernel** (top right), choose **Python Environments**, and pick `analysis\.venv\Scripts\python.exe` (shown as `.venv`). If it is not listed, use **Python: Select Interpreter** > **Enter interpreter path** with that path. The Jupyter and Python extensions are needed; `ipykernel` comes with `jupyterlab`.

Notebook outputs can contain personal data, so `.gitattributes` strips them on commit with `nbstripout`. Set up the filter once per clone (from the repository root):

```sh
git config filter.nbstripout.clean "uv run --directory analysis nbstripout"
git config filter.nbstripout.smudge cat
git config filter.nbstripout.required true
git config diff.ipynb.textconv "uv run --directory analysis nbstripout -t"
```

## Privacy

No credentials, raw activity files, or databases are committed. API keys and session tokens live in the data directory outside the repository. The physiology parameters in the docs (HRmax, resting HR, LTHR) are the author's own and are kept because the design decisions depend on them.

## License

[MIT](LICENSE)
