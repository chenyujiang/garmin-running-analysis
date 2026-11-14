"""Compile the dashboard stylesheet with the Tailwind CSS standalone CLI.

Source `src/running/dashboard/styles/tailwind.css`, output
`src/running/dashboard/static/style.css` (committed, so the dashboard needs
no build step). The CLI is a pinned release binary kept in `tools/` (not
committed): downloaded from GitHub on first run and checked against the
SHA-256 below before it is ever executed.

Run from analysis/:  uv run python scripts/build_css.py
                     uv run python scripts/build_css.py --check   (CI: fail when style.css is stale)
"""

import hashlib
import platform
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

VERSION = "v4.3.5"
# sha256sums.txt of the release, one entry per platform this repo is built on
SHA256 = {
    "windows-x64.exe": "2803583268c53f4713e89943e211081fddb186c0a4a7d07b5c342c6ae853ec95",
    "linux-x64": "e47695cee3f0d90623a91f3939b08bdee610eb5ad99340adff9d4145b284d6cc",
    "linux-arm64": "ffcd0d21dbd7c605dc12743ff0c0b47debc963c86b399674084c1c8f2c96ecad",
    "macos-x64": "a63702686a3ed048b3135d84a73be49ea9d47f880c9b20e54b3ef60934ad8cdf",
    "macos-arm64": "f3f4f5d1727e2b693b8f1c9a1492b5dd87008c86ea286bee1589cb458e6235fc",
}
ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
DASHBOARD = ROOT / "src" / "running" / "dashboard"
SOURCE = DASHBOARD / "styles" / "tailwind.css"
OUTPUT = DASHBOARD / "static" / "style.css"


def asset() -> str:
    system = {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}.get(platform.system())
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(
        platform.machine().lower()
    )
    name = f"{system}-{arch}" + (".exe" if system == "windows" else "")
    if name not in SHA256:
        raise SystemExit(f"no pinned Tailwind CLI for {platform.system()} {platform.machine()}")
    return name


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cli() -> Path:
    name = asset()
    path = TOOLS / f"tailwindcss-{VERSION}-{name}"
    if path.exists() and sha256(path) == SHA256[name]:
        return path
    url = f"https://github.com/tailwindlabs/tailwindcss/releases/download/{VERSION}/tailwindcss-{name}"
    print(f"downloading {url}", file=sys.stderr)
    TOOLS.mkdir(exist_ok=True)
    part = path.with_name(path.name + ".part")
    with urllib.request.urlopen(url, timeout=120) as r:
        part.write_bytes(r.read())
    if sha256(part) != SHA256[name]:
        part.unlink()
        raise SystemExit(f"SHA-256 mismatch for {url}; not using it")
    part.chmod(0o755)
    part.replace(path)
    return path


def build(out: Path) -> None:
    subprocess.run([str(cli()), "-i", str(SOURCE), "-o", str(out)], check=True, capture_output=True)


def lf(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def main() -> None:
    if sys.argv[1:] == ["--check"]:
        with tempfile.TemporaryDirectory() as tmp:
            fresh = Path(tmp) / "style.css"
            build(fresh)
            # the CLI writes LF; a checkout with core.autocrlf has CRLF
            if lf(fresh) != lf(OUTPUT):
                raise SystemExit(
                    "static/style.css is out of date: run `uv run python scripts/build_css.py`"
                )
        print("style.css is up to date")
    elif not sys.argv[1:]:
        build(OUTPUT)
        print(f"wrote {OUTPUT.relative_to(ROOT)}")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
