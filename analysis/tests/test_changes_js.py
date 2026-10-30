"""Seam: the "changed since last read" tracker in `static/changes.js`.

The tracker is plain JavaScript run in the browser, so its tests are
`node --test` files in `tests/js/`. This wrapper runs them as part of
`uv run pytest`; it is skipped when Node.js is not installed.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

JS_TESTS = Path(__file__).resolve().parent / "js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_changes_tracker_js():
    files = sorted(str(p) for p in JS_TESTS.glob("*.test.mjs"))
    assert files, "no JS test files found"
    result = subprocess.run(
        ["node", "--test", *files],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
