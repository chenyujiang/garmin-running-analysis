"""Seam: the example notebook `notebooks/explore.ipynb`.

It must run top to bottom against a data directory (here a synthetic one via
`RUNNING_DATA_DIR`), call only the package's public functions, and be stored
in git without outputs.
"""

import ast
from datetime import date, timedelta
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from synthetic_aerobic import add_hr_run, steady

NOTEBOOK = Path(__file__).resolve().parents[1] / "notebooks" / "explore.ipynb"


def code_cells(nb) -> list[str]:
    return [c.source for c in nb.cells if c.cell_type == "code"]


def test_notebook_runs_against_a_synthetic_data_dir(analysis_db, data_dir):
    today = date.today()
    for i in range(6):
        day = today - timedelta(days=3 * i)
        add_hr_run(analysis_db, i + 1, f"{day.isoformat()}T07:00:00", [steady(1800)])

    nb = nbformat.read(NOTEBOOK, as_version=4)
    NotebookClient(nb, timeout=120, kernel_name="python3").execute()

    errors = [o for c in nb.cells for o in c.get("outputs", []) if o.output_type == "error"]
    assert errors == []
    text = "".join(
        o.get("text", "")
        for c in nb.cells
        for o in c.get("outputs", [])
        if o.output_type == "stream"
    )
    assert str(data_dir) in text
    assert "EF:" in text


def test_notebook_runs_with_no_database_yet(data_dir):
    nb = nbformat.read(NOTEBOOK, as_version=4)
    NotebookClient(nb, timeout=120, kernel_name="python3").execute()

    errors = [o for c in nb.cells for o in c.get("outputs", []) if o.output_type == "error"]
    assert errors == []


def test_notebook_uses_only_public_running_names():
    nb = nbformat.read(NOTEBOOK, as_version=4)
    for src in code_cells(nb):
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("running"):
                for alias in node.names:
                    assert not alias.name.startswith("_"), alias.name
            if isinstance(node, ast.Attribute):
                assert not node.attr.startswith("_"), node.attr
            if isinstance(node, ast.Import | ast.ImportFrom):
                mods = [a.name for a in node.names] if isinstance(node, ast.Import) else []
                mods.append(getattr(node, "module", None) or "")
                # Computation goes through `running`; no direct SQL engines.
                assert not any(m.split(".")[0] in {"duckdb", "sqlite3"} for m in mods), mods


def test_committed_notebook_has_no_outputs():
    nb = nbformat.read(NOTEBOOK, as_version=4)
    for c in nb.cells:
        if c.cell_type == "code":
            assert c.outputs == []
            assert c.execution_count is None
