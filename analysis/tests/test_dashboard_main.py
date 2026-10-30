"""Seam: the `running-dashboard` entry point.

The startup line contains Chinese; a console whose stdout is not UTF-8
(Windows cp1252, a redirected pipe) must not crash the dashboard.
"""

import io
import sys

import uvicorn

from running.dashboard import app


def test_starts_on_a_console_that_cannot_encode_chinese(monkeypatch):
    raw = io.BytesIO()
    stdout = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", stdout)
    started = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: started.append(kw))

    app.main()

    sys.stdout.flush()
    assert started == [{"host": app.HOST, "port": app.PORT}]
    assert f"http://{app.HOST}:{app.PORT}/".encode() in raw.getvalue()
