"""Build `src/running/parkrun_courses.json`: a 5 km elevation profile for every
parkrun in the Auckland region, for the parkrun course page (#/parkruns).

    python -I scripts/build_parkrun_courses.py WORK_DIR [OUT]

Steps, all with the standard library only:

1. Download each event's official course page from parkrun.co.nz and the
   Google My Maps course map it embeds (as KML) into WORK_DIR. Files already
   there are reused. They are untrusted input: run this with `python -I` and
   keep WORK_DIR outside the repository.
2. Resample the drawn course line every 10 m and look up ground elevation
   from the OpenTopoData public API, dataset `nzdem8m` (LINZ 8 m DEM of New
   Zealand). Answers are cached in WORK_DIR.
3. The DEM is bare earth, so a footbridge or a path over a motorway shows a
   dip to the water or road below. A morphological closing over 120 m fills
   dips narrower than that; a 60 m moving average then removes DEM noise.
4. Lay the line out as the course is run (laps, out-and-backs; see LAYOUT,
   taken from the official course descriptions), scale it to 5000 m and
   store the elevation every 25 m.

The output holds elevations and distances only: no coordinates.
"""

import json
import math
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (parkrun course profile builder)"}
KML_NS = "{http://www.opengis.net/kml/2.2}"
STEP_LINE_M = 10.0
STEP_OUT_M = 25.0
CLOSING_M = 120.0
SMOOTH_M = 60.0
COURSE_M = 5000.0

# How the drawn line is run, from each official course description:
#   "full"  the map draws the whole 5 km in running order
#   "loop"  the map draws one lap; laps start where the line passes the start
#   tokens  "@" the start, "A"/"B" the ends of the drawn line, "N"/"S"/"E"/"W"
#           the end farthest in that direction, "FAR" the end farther from the
#           start. The run goes from token to token along the line; the
#           sequence repeats until 5 km if it is shorter.
LAYOUT = {
    "barrycurtis": "full",
    "cornwallpark": "loop",
    "hobsonvillepoint": "full",
    "mangerebridge": "@ E W E @",
    "millwater": "@ FAR @",
    "northernpathway": "@ N S @",
    "opahekepark": "loop",
    "orakeibay": "@ FAR @",
    "owairaka": "full",
    "parrspark": "@ FAR @",
    "sherwoodreserve": "loop",
    "southernpath": "@ N S @",
    "sunnynook": "loop",
    "tuffcraterreserve": "full",
    "warkworthshowgrounds": "@ FAR @",
    "westernsprings": "loop",
}


def fetch(url: str, path: Path) -> Path:
    if not path.exists():
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            path.write_bytes(r.read())
        time.sleep(1.0)
    return path


def course_map_id(html: str) -> str:
    i = html.find("google.com/maps/d/")
    j = html.find("mid=", i)
    if i < 0 or j < 0:
        raise ValueError("no Google My Maps course map on the course page")
    k = j + 4
    while k < len(html) and html[k] not in "\"'&<> ":
        k += 1
    return html[j + 4 : k]


def hav(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Metres between (lon, lat) points."""
    lo1, la1, lo2, la2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    x = (
        math.sin((la2 - la1) / 2) ** 2
        + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    )
    return 2 * 6371000 * math.asin(math.sqrt(x))


def read_kml(path: Path) -> tuple[list[tuple[float, float]], tuple[float, float] | None]:
    """The longest line and the start point (a point named like "Start")."""
    root = ET.parse(path).getroot()
    line: list[tuple[float, float]] = []
    start = None
    for pm in root.iter(KML_NS + "Placemark"):
        name = (pm.findtext(KML_NS + "name") or "").lower()
        for ls in pm.iter(KML_NS + "LineString"):
            text = ls.findtext(KML_NS + "coordinates") or ""
            pts = [tuple(map(float, c.split(",")[:2])) for c in text.split()]
            if len(pts) > len(line):
                line = pts
        pt = pm.find(f".//{KML_NS}Point")
        if pt is not None and "start" in name and start is None:
            start = tuple(map(float, (pt.findtext(KML_NS + "coordinates") or "").split(",")[:2]))
    if len(line) < 2:
        raise ValueError(f"{path.name}: no course line")
    return line, start


def resample(line: list[tuple[float, float]], step: float) -> list[tuple[float, float]]:
    out = [line[0]]
    carry = 0.0
    for a, b in zip(line, line[1:], strict=False):
        d = hav(a, b)
        t = step - carry
        while t <= d:
            f = t / d
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
            t += step
        carry = d - (t - step)
    if hav(out[-1], line[-1]) > step / 4:
        out.append(line[-1])
    return out


def elevations(pts: list[tuple[float, float]], cache_path: Path) -> list[float]:
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    keys = [f"{p[1]:.6f},{p[0]:.6f}" for p in pts]
    todo = [k for k in dict.fromkeys(keys) if k not in cache]
    for i in range(0, len(todo), 100):
        batch = todo[i : i + 100]
        url = "https://api.opentopodata.org/v1/nzdem8m?locations=" + urllib.parse.quote(
            "|".join(batch), safe=",|"
        )
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
            res = json.load(r)
        if res.get("status") != "OK":
            raise RuntimeError(f"OpenTopoData: {res.get('error') or res.get('status')}")
        for k, item in zip(batch, res["results"], strict=True):
            cache[k] = item["elevation"]  # None over water (a wharf, a boardwalk)
        cache_path.write_text(json.dumps(cache))
        time.sleep(1.2)
    return fill_gaps([cache[k] for k in keys])


def fill_gaps(values: list[float | None]) -> list[float]:
    """Interpolate points the DEM has no value for from their neighbours."""
    known = [i for i, v in enumerate(values) if v is not None]
    if not known:
        raise RuntimeError("OpenTopoData: no elevation anywhere on the line")
    out = []
    for i, v in enumerate(values):
        if v is not None:
            out.append(float(v))
            continue
        lo = max((j for j in known if j < i), default=None)
        hi = min((j for j in known if j > i), default=None)
        if lo is None or hi is None:
            out.append(float(values[hi if lo is None else lo]))
        else:
            out.append(values[lo] + (values[hi] - values[lo]) * (i - lo) / (hi - lo))
    return out


def window(values: list[float], half: int, fn) -> list[float]:
    n = len(values)
    return [fn(values[max(0, i - half) : min(n, i + half + 1)]) for i in range(n)]


def clean(ele: list[float]) -> list[float]:
    """Fill bridge dips (closing: max then min filter), then smooth."""
    half = round(CLOSING_M / STEP_LINE_M / 2)
    closed = window(window(ele, half, max), half, min)
    return window(closed, round(SMOOTH_M / STEP_LINE_M / 2), lambda w: sum(w) / len(w))


def nearest_index(pts: list[tuple[float, float]], p: tuple[float, float]) -> int:
    return min(range(len(pts)), key=lambda i: hav(pts[i], p))


def lay_out(layout: str, pts, ele: list[float], start) -> tuple[list[float], str | None]:
    """Elevation every STEP_LINE_M in running order, and a note on the fit."""
    n = len(ele)
    s = nearest_index(pts, start) if start else 0
    passes = 1
    if layout == "full":
        seq = list(ele)
    elif layout == "loop":
        lap = ele[s:] + ele[:s]
        seq = []
        while len(seq) * STEP_LINE_M < COURSE_M:
            seq += lap
        passes = 2  # always cut at 5 km
    else:
        ends = {"A": 0, "B": n - 1}
        ends["N"] = 0 if pts[0][1] > pts[-1][1] else n - 1
        ends["S"] = n - 1 - ends["N"]
        ends["E"] = 0 if pts[0][0] > pts[-1][0] else n - 1
        ends["W"] = n - 1 - ends["E"]
        ends["FAR"] = 0 if hav(pts[0], pts[s]) > hav(pts[-1], pts[s]) else n - 1
        ends["@"] = s
        marks = [ends[t] for t in layout.split()]
        rep = []
        for a, b in zip(marks, marks[1:], strict=False):
            rep += ele[a : b + 1] if a <= b else ele[b : a + 1][::-1]
        seq = []
        while len(seq) * STEP_LINE_M < COURSE_M * 0.95:
            seq += rep
        passes = len(seq) // len(rep)
    drawn_m = len(seq) * STEP_LINE_M
    # A lap or a repeated out-and-back is cut at 5 km; a course drawn once
    # (in full or as one pass through the tokens) is scaled to 5 km.
    if passes > 1 and drawn_m > COURSE_M:
        return seq[: round(COURSE_M / STEP_LINE_M) + 1], None
    note = None
    if abs(drawn_m - COURSE_M) > 0.1 * COURSE_M:
        note = f"官方地图线路按描述拼出 {drawn_m / 1000:.1f} km，已按比例缩放到 5 km"
    return seq, note


def to_course(seq: list[float]) -> list[float]:
    """Scale to 5000 m and sample every STEP_OUT_M."""
    n = len(seq) - 1
    out = []
    for k in range(round(COURSE_M / STEP_OUT_M) + 1):
        x = k * STEP_OUT_M / COURSE_M * n
        i = min(int(x), n - 1)
        f = x - i
        out.append(round(seq[i] + (seq[i + 1] - seq[i]) * f, 1))
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    work = Path(sys.argv[1])
    out = (
        Path(sys.argv[2])
        if len(sys.argv) > 2
        else (Path(__file__).resolve().parent.parent / "src" / "running" / "parkrun_courses.json")
    )
    work.mkdir(parents=True, exist_ok=True)
    courses = {}
    for slug, layout in LAYOUT.items():
        page = fetch(f"https://www.parkrun.co.nz/{slug}/course/", work / f"{slug}.html")
        mid = course_map_id(page.read_text(encoding="utf-8", errors="replace"))
        kml = fetch(
            f"https://www.google.com/maps/d/kml?mid={urllib.parse.quote(mid)}&forcekml=1",
            work / f"{slug}.kml",
        )
        line, start = read_kml(kml)
        pts = resample(line, STEP_LINE_M)
        ele = clean(elevations(pts, work / f"{slug}.elevation.json"))
        seq, note = lay_out(layout, pts, ele, start)
        courses[slug] = {"elevation_m": to_course(seq), "fit_note": note}
        print(
            f"{slug}: {len(seq) * STEP_LINE_M / 1000:.2f} km laid out{f' ({note})' if note else ''}"
        )
    data = {
        "source": (
            "parkrun.co.nz course pages and maps; elevation: OpenTopoData nzdem8m (LINZ 8 m DEM)"
        ),
        "step_m": STEP_OUT_M,
        "courses": courses,
    }
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
