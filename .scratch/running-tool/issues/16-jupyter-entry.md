# 16: Jupyter exploration entry point

**What to build:** The user opens an example notebook with `uv run jupyter lab`, calls the same public functions as the dashboard to look at aerobic fitness, load and weekly volume, and explores further from there.

**Blocked by:** 11 (aerobic fitness computation and interface)

**Status:** done

Source: User Stories 47 and 48 in the [implementation spec](../spec.md).

- [x] `jupyterlab` is in the Python project's dev dependency group
- [x] The example notebook only calls the analysis package's public functions and copies no computation logic
- [x] `nbstripout` clears outputs on commit; confirm the notebook in git holds no personal data
- [x] The README explains how to start Jupyter and how to pick the kernel in VS Code

## Outcome

- `jupyterlab` and `nbstripout` went into the dev group of `analysis/pyproject.toml` back in ticket 02; the nbstripout filter in `.gitattributes` was already in place too.
- Example notebook: `analysis/notebooks/explore.ipynb`. In order it shows the data status, weekly volume (`weekly_volume`), training load (`training_load`), aerobic fitness (`aerobic_trend`) and the per-run tables (`running_summaries`, `aerobic_runs`), and finally uses `load_records` + `steady_state` to show the per-second steady segments and EF of one road run. Without a database every cell still runs and shows empty tables.
- Test `analysis/tests/test_notebook.py`: `nbclient` runs the notebook end to end, with no errors, in a temporary `RUNNING_DATA_DIR` (synthetic road runs) and with no database yet. A static check makes sure the code cells import only public names from `running`, touch no attributes starting with `_`, and use neither `duckdb` nor `sqlite3` directly; the committed notebook has no outputs and empty `execution_count`s.
- The README's Notebooks section gives `uv run jupyter lab notebooks/explore.ipynb` and the steps to pick the `analysis\.venv` kernel in VS Code.
- The notebook draws no charts: the analysis package has no plotting dependency, and tables use polars' own HTML display. Whether to add altair or something else is decided when charts are needed.
