"""Console output for the command-line entry points."""

import io
import sys


def utf8_stdio() -> None:
    """Write stdout and stderr as UTF-8, replacing anything unencodable: a
    console or pipe that is not UTF-8 (e.g. cp1252) cannot encode Chinese."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")
