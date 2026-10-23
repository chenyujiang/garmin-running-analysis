# garmin-running-analysis

A personal running analysis tool for one Garmin account. It pulls the full activity history (per-second FIT data, daily summaries, and a few Garmin metrics) into a local archive, then computes its own transparent, tunable metrics instead of relying on Garmin's black-box numbers:

- **Aerobic fitness trend**: grade-adjusted pace at a fixed reference heart rate, fitted on steady-state seconds of each run, shown as weekly medians with a 4-week rolling median.
- **Training load**: Banister TRIMP per activity, CTL/ATL/TSB trends, and a load-spike warning.
- **Weekly volume**: running and walking distance per week.
- **Race prediction**: VDOT from recent all-out races, with Riegel and Garmin's Race Predictor for comparison.

Every number links back to a documented formula and configurable parameters. Garmin's own figures appear only as a reference.

## Status

Planning is done; implementation has not started. This repository currently holds the design work:

| Path | Contents |
|---|---|
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

## Privacy

No credentials, raw activity files, or databases are committed. API keys and session tokens live in the data directory outside the repository. The physiology parameters in the docs (HRmax, resting HR, LTHR) are the author's own and are kept because the design decisions depend on them.

## License

[MIT](LICENSE)
