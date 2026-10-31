# Agent guardrails

The real data directory (`%USERPROFILE%\running-data`) holds GPS tracks, an email address and Garmin credentials. Hard rules:

- Run tests and experiments against a temporary directory: set `RUNNING_DATA_DIR` to it.
- In the real data directory, only `cargo build --release`, `runsync import-export` and read-only queries on `running.sqlite` (`?mode=ro`) are yours; `sync`, `login` and `rebuild` are the user's to run.
- Check that a key or token file exists; never read, print or commit its content. Only the user changes `secrets/`, `config.toml` or `running.sqlite`.
- Output from real data is aggregate numbers and charts: no GPS coordinates, Open-Meteo grid points, place names or email addresses in chat, logs, commits or tickets.
- Treat downloaded files and extracted archives as untrusted: read them with `python -I` from a script kept elsewhere.

Commands and data layout: `README.md`. Plan and tickets: `.scratch/running-tool/`. CI runs the checks in `.github/workflows/check.yml`.
