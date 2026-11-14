# Personal running data analysis (Garmin)

Label: wayfinder:map

## Destination

A technical plan ready to start work on: how to get all data out of Garmin Connect (international), where to store it, which stack to use, and how each of the three core analyses (aerobic fitness, weekly volume and training load, race prediction) is computed. Implementation is outside this map.

## Notes

- Domain: personal sports data analysis, single user, running locally.
- Account: Garmin Connect international (garmin.com), MFA not enabled.
- Languages: the data import CLI (pull, parse FIT, write to storage) is Rust, because the user wants to learn Rust through it; analysis is Python. The two sides exchange data only through storage.
- Analysis: Jupyter notebooks for exploration; plus a local dashboard.
- Design: every ticket touching the interface uses `impeccable`.
- Data access: the risk of unofficial libraries is accepted, with rate limiting; manual FIT export / account data export as fallback. (Specific routes in Decisions so far.)
- Credentials: only tokens / API keys are stored locally; passwords never touch disk.
- Data scope: running activities (per-second streams, not just summaries) + HRV, resting heart rate, sleep. About 5 years of history, all of it.
- The user does not wear the watch while sleeping: HRV and sleep effectively have no data (the trial pull found the last 30 days all empty); resting heart rate comes only from daytime wear, with some days missing.
- Sync: backfill all history once first, then sync incrementally.
- Algorithms: Garmin's own metrics (Training Load, VO2max, Race Predictor) as reference; the main models are our own (transparent, tunable).
- References for every session: `grilling`, `domain-modeling`; terms are in `GLOSSARY.md` at the root.

## Decisions so far

<!-- the index: one line per closed ticket -->

- [Survey of Garmin Connect data access routes](issues/01-garmin-data-access.md): the official Personal API is the workhorse (activities, FIT, HRV, sleep, resting heart rate); `garminconnect` only fills in Training Load / VO2max / Race Predictor; the account data export serves as the archive of original FIT files; `garth` is deprecated.
- [Survey of methods for aerobic fitness, training load and race prediction](issues/02-analysis-methods.md): recommends GAP pace at a fixed heart rate + EF/decoupling; Banister TRIMP + CTL/ATL/TSB; VDOT as main with Riegel as comparison, plus a volume correction for the marathon; needs measured HRmax, LTHR and a hand-kept race list.
- [How the Rust import CLI calls the Garmin APIs](issues/10-rust-api-coverage.md): the Personal API is hand-written with `reqwest` (no existing crate, and the spec lacks `operationId`); the three Garmin metrics go to a small Python script called with `uv run`, without rewriting login in Rust; FIT is parsed with `fitparser`, raw bytes written to disk first.
- [Trial pull of a small batch of real data](issues/03-trial-pull.md): about 200 Personal API requests were not rate-limited; activities go back to 2021-08-06 (about 1000–1500); downloaded FIT files match the originals byte for byte; `garminconnect`'s mobile login got a 429, but after falling back to the backup strategy login succeeded and all three metrics were fetched.
- [Storage design](issues/04-storage.md): the raw archive (FIT, JSON) is kept as is in a data directory outside the repository and is the source of truth; the analysis database is SQLite (WAL), with Rust defining the schema and writing, Python reading only, rebuildable from the raw archive at any time; all activity types are stored, per-second data in one long table.
- [Backfill and incremental sync strategy](issues/05-sync-strategy.md): the import CLI has only three commands, `sync`, `login` and `rebuild`; triggered by hand; serial and rate-limited, resuming based on whether raw files already exist, with no stored progress; each run re-pulls the last 7 days to pick up corrections; a 429 stops at once and cools down for 24 hours, and the two data sources do not affect each other.
- [Definition of the aerobic fitness metric](issues/06-aerobic-metric.md): the main metric is GAP pace at the reference heart rate of 145 bpm (each run fits a speed–heart rate line on its steady-state segments); each second is classified as running or walking by cadence, and pace and weekly volume count only running; only outdoor road runs count; grade corrected with Minetti, temperature not corrected in the first version, only shown; weekly medians plus a 4-week rolling trend line.
- [Training load model and race prediction method](issues/07-load-and-prediction.md): every activity with heart rate gets a per-second Banister TRIMP (HRmax 192, HRrest 55 fixed, parameters configured by effective date); CTL 42/ATL 7/TSB only as relative measures; weekly volume counts all runs by calendar week; race prediction uses a hand-kept `races.csv`, VDOT as main with Riegel as comparison, a weekly-volume correction for the marathon, and Garmin's prediction as reference.
- [Project skeleton and dependencies](issues/11-project-skeleton.md): the repository holds two projects, `importer/` (Rust CLI `runsync`, blocking reqwest, hand-written `user_version` migrations) and `analysis/` (uv, Python 3.14, polars + DuckDB, Jupyter); personal data, `config.toml`, `races.csv` and keys all live in the data directory outside the repository that `RUNNING_DATA_DIR` points to.
- [Design of the analysis dashboard](issues/08-dashboard-design.md): newspaper sports-section visual style; layout variant A (first screen three columns: load, weekly volume, race prediction; below it a full-width aerobic trend chart with crosshair readout), handling three states: not synced, prediction stale, too little data; tech stack FastAPI plus a static frontend (hand-written SVG), since Streamlit cannot reproduce the annotations and typography; the prototype is on the `prototype/dashboard` branch.

## Not yet specified

(None. The remaining two items moved to the closing notes below, for the implementation phase.)

## Out of scope

- Writing the code of the analysis tool: this map only produces the plan.
- Multiple users, cloud deployment, phone access: for my own local use only.
- Garmin's official Connect Developer Program: only open to businesses, unrealistic for an individual to apply.

## Closing notes

2026-10-24: everything on the map that needed deciding up front is decided, and implementation can start. The two items below can only be judged with all the real data, so they are left for the implementation phase: once the first `runsync sync` backfill completes, open new tickets to decide them.

- **Data quality and cleaning**: optical heart-rate artefacts, GPS drift, manual and auto pauses on the watch, treadmill activities. After the backfill, first count each of these problems in Jupyter, then decide which to filter in `analysis/src/running/` and how.
- **Temperature correction**: the first version of aerobic fitness does not correct for temperature; the trend chart only shows weekly mean temperature. Once the full history is available, look at the size of the seasonal swing, then decide whether to regress against external historical air temperature.

One more item does not affect implementation: [Request a Garmin account data export](issues/09-account-export.md); fill in the Answer once the user has requested it on the Garmin website and the export package has arrived.
