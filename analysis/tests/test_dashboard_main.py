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


def test_static_files_are_revalidated_before_reuse(client_factory):
    client = client_factory()
    for path in ("/", "/style.css", "/app.js"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-cache"
        assert "etag" in r.headers
    etag = client.get("/style.css").headers["etag"]
    assert client.get("/style.css", headers={"If-None-Match": etag}).status_code == 304
