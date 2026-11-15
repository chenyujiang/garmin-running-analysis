"""Print the layout of a Garmin account export zip, for checks on real data:
per folder the file count by extension, redacted file name patterns and the
range of dates found in the names; nested zips (the uploaded FIT parts) are
listed the same way.

Reads only the zip directories, in memory: nothing is extracted and no
member is opened except a nested zip, whose directory is read the same way.
Names are redacted before printing: anything up to and including an email
address becomes `<email>`, ISO dates `<date>`, UUIDs `<uuid>` and runs of 3
or more digits `<n>`.

Standard library only, so it runs isolated (the export is untrusted):
  python -I analysis/scripts/export_summary.py [zip ...]
Without arguments it reads every zip under raw/export/ in the data
directory (RUNNING_DATA_DIR, default %USERPROFILE%/running-data).
"""

import io
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

# How deep nested zips are listed, and the largest nested zip read into memory.
MAX_DEPTH = 2
MAX_NESTED_BYTES = 1 << 30

_EMAIL = re.compile(r"^.*@[A-Za-z0-9.-]+")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_DIGITS = re.compile(r"\d{3,}")
TOP_PATTERNS = 5


def redact(part: str) -> str:
    """One path component with private values replaced by placeholders."""
    part = _EMAIL.sub("<email>", part)
    part = _UUID.sub("<uuid>", part)
    part = _DATE.sub("<date>", part)
    return _DIGITS.sub("<n>", part)


def _redact_path(path: PurePosixPath) -> str:
    return "/".join(redact(p) for p in path.parts) or "."


def zip_lines(z: zipfile.ZipFile, indent: str = "", depth: int = 0) -> list[str]:
    exts: dict[str, Counter] = defaultdict(Counter)
    names: dict[str, Counter] = defaultdict(Counter)
    dates: dict[str, list[str]] = defaultdict(list)
    nested: list[str] = []
    for info in z.infolist():
        if info.is_dir():
            continue
        path = PurePosixPath(info.filename)
        folder = _redact_path(path.parent)
        ext = path.suffix.lower() or "(none)"
        exts[folder][ext] += 1
        names[folder][redact(path.name)] += 1
        dates[folder] += _DATE.findall(path.name)
        if ext == ".zip":
            label = f"{indent}nested {folder}/{redact(path.name)}"
            if depth >= MAX_DEPTH:
                nested.append(f"{label}: not listed (depth)")
            elif info.file_size > MAX_NESTED_BYTES:
                nested.append(f"{label}: not listed ({info.file_size} bytes)")
            else:
                with zipfile.ZipFile(io.BytesIO(z.read(info))) as inner:
                    nested.append(f"{label}:")
                    nested += zip_lines(inner, indent + "  ", depth + 1)

    lines = []
    for folder in sorted(exts):
        counts = ", ".join(f"{e} {n}" for e, n in sorted(exts[folder].items()))
        lines.append(f"{indent}{folder}: {counts}")
        top = names[folder].most_common(TOP_PATTERNS)
        more = len(names[folder]) - len(top)
        patterns = ", ".join(f"{p} x{n}" for p, n in top)
        lines.append(f"{indent}  names: {patterns}" + (f" (+{more} more)" if more > 0 else ""))
        if dates[folder]:
            lines.append(f"{indent}  dates in names: {min(dates[folder])} .. {max(dates[folder])}")
    totals: Counter = Counter()
    for c in exts.values():
        totals.update(c)
    lines.append(f"{indent}total: " + ", ".join(f"{e} {n}" for e, n in sorted(totals.items())))
    return lines + nested


def summary(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        size = path.stat().st_size
        return "\n".join([f"{redact(path.name)} ({size} bytes)", *zip_lines(z)])


def _default_zips() -> list[Path]:
    # Same lookup as running.config.data_dir, which this script cannot import.
    value = os.environ.get("RUNNING_DATA_DIR")
    home = os.environ.get("USERPROFILE") or str(Path.home())
    root = Path(value) if value else Path(home) / "running-data"
    return sorted((root / "raw" / "export").glob("*/*.zip"))


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv] or _default_zips()
    if not paths:
        print("no export zip found under raw/export/", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n\n".join(summary(p) for p in paths))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
