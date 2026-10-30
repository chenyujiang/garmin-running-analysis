# garmin-running-analysis

A personal running analysis tool for one Garmin account. It pulls the full activity history (per-second FIT data, daily summaries, and a few Garmin metrics) into a local archive, then computes its own transparent, tunable metrics instead of relying on Garmin's black-box numbers:

- **Aerobic fitness trend**: grade-adjusted pace at a fixed reference heart rate, fitted on steady-state seconds of each run, shown as weekly medians with a 4-week rolling median.
- **Training load**: Banister TRIMP per activity, CTL/ATL/TSB trends, and a load-spike warning.
- **Weekly volume**: running and walking distance per week.
- **Race prediction**: VDOT from recent all-out races, with Riegel and Garmin's Race Predictor for comparison.

Every number links back to a documented formula and configurable parameters. Garmin's own figures appear only as a reference.

## Status

Implementation is under way, one ticket at a time (see `.scratch/running-tool/issues/`). The skeleton is in place: `runsync rebuild` turns a raw archive into the analysis database, and the dashboard shows either an empty state or the activity count and last sync time. `runsync sync` and `runsync login` exist but only print "not implemented yet".

| Path | Contents |
|---|---|
| `importer/` | Rust crate, binary `runsync` |
| `analysis/` | uv-managed Python 3.14 project, package `running` (analysis code and dashboard) |
| `.scratch/running-analysis/map.md` | Decision map: every design question and how it was resolved |
| `.scratch/running-analysis/issues/` | One file per decision (data access, analysis methods, storage, sync, metrics, dashboard design) |
| `.scratch/running-tool/spec.md` | Implementation spec: user stories, architecture, schema, testing seams |
| `.scratch/running-tool/issues/` | The spec broken into 16 vertical-slice tickets |
| `GLOSSARY.md`, `PRODUCT.md` | Domain vocabulary and product context |

Supporting material lives on branches that are never merged:

- `research/garmin-data-access`, `research/analysis-methods`, `research/rust-api-coverage`: research reports
- `prototype/dashboard`: throwaway dashboard prototypes (a static HTML version and a Streamlit comparison), using synthetic data

Most documents are written in Chinese.

## Planned architecture

- **Rust CLI (`runsync`)**: syncs from the official Garmin Connect Personal API, stores raw FIT and JSON files unchanged in a data directory outside the repository, and builds a SQLite analysis database from them.
- **Python analysis package**: polars and DuckDB over the read-only analysis database; also usable from Jupyter.
- **Dashboard**: FastAPI bound to `127.0.0.1`, serving JSON to a static frontend (plain HTML, native ES modules, hand-written SVG charts).

## Data directory

Both projects find their data through `RUNNING_DATA_DIR`, defaulting to `%USERPROFILE%\running-data`. It holds `config.toml`, the raw archive (`raw/`), credentials (`secrets/`) and the analysis database `running.sqlite`. Minimal `config.toml`:

```toml
[aerobic]
reference_hr = 145

[[physiology]]
effective_from = 2021-08-01
hr_max = 192
hr_rest = 55
lthr = 170

[sync]
personal_api_interval_s = 1.5   # pause between Personal API requests (default 1.5)
```

`runsync sync` reads the Personal API key from `secrets/personal_api.key` (the bare key on one line; generate it at https://connect.garmin.com/app/settings/personalApiToken). It downloads every activity's detail JSON and FIT into `raw/personal_api/activities/`, loading each file into `running.sqlite` straight away. Rerun it after an interruption to resume. Later runs fetch only new activities and refetch details from the last 7 days.

## Common commands

Importer (run in `importer/`):

```sh
cargo build --release          # binary at target/release/runsync.exe
cargo run -- sync              # fetch new activities from the Personal API (RUST_LOG=debug for detail)
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
