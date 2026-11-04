"""Seam 3: the route shape of GET /api/activities/{activity_id}.

The route is drawn from its GPS seconds as a normalised shape only: x, y in
[0, 1] with the aspect ratio kept, at most 500 points, the start and finish
indices and a scale in metres per unit. No absolute latitude, longitude or
centre point leaves the server. A run without GPS has `route: null` and the
reason.

The coordinates below are fictional (open ocean in the South Pacific), not
anyone's running spot.
"""

import math
from collections.abc import Iterator

import pytest
from synthetic import insert_activity
from synthetic_route import LatLon, add_route_run

ORIGIN_LAT = -31.7
ORIGIN_LON = -128.3
EARTH_RADIUS_M = 6_371_008.8
START_LOCAL = "2026-10-20T07:00:00"


def at(east_m: float, north_m: float) -> tuple[float, float]:
    """The fictional point `east_m`, `north_m` metres from the origin."""
    lat = ORIGIN_LAT + math.degrees(north_m / EARTH_RADIUS_M)
    lon = ORIGIN_LON + math.degrees(east_m / (EARTH_RADIUS_M * math.cos(math.radians(ORIGIN_LAT))))
    return lat, lon


def rectangle_loop(width_m: float, height_m: float, step_m: float = 3.0) -> list[LatLon]:
    """Anticlockwise from the south-west corner: east, north, west, south."""
    corners = [(0, 0), (width_m, 0), (width_m, height_m), (0, height_m), (0, 0)]
    track: list[LatLon] = []
    for (e0, n0), (e1, n1) in zip(corners, corners[1:], strict=False):
        steps = round(math.hypot(e1 - e0, n1 - n0) / step_m)
        track += [at(e0 + (e1 - e0) * i / steps, n0 + (n1 - n0) * i / steps) for i in range(steps)]
    return [*track, at(0, 0)]


def numbers(value) -> Iterator[float]:
    """Every number anywhere in a JSON value."""
    if isinstance(value, bool):
        return
    if isinstance(value, int | float):
        yield float(value)
    elif isinstance(value, dict):
        for v in value.values():
            yield from numbers(v)
    elif isinstance(value, list):
        for v in value:
            yield from numbers(v)


def assert_no_coordinates(body: dict, track: list[LatLon]) -> None:
    """No number anywhere in the response is within 0.5 degree of a raw
    latitude or longitude, sign ignored."""
    fixes = [fix for fix in track if fix is not None]
    windows = []
    for axis in (0, 1):
        raw = [abs(fix[axis]) for fix in fixes]
        windows.append((min(raw) - 0.5, max(raw) + 0.5))
    for n in numbers(body):
        assert not any(lo <= abs(n) <= hi for lo, hi in windows), n


def get_detail(client_factory, activity_id: int) -> dict:
    r = client_factory().get(f"/api/activities/{activity_id}")
    assert r.status_code == 200, r.text
    return r.json()


def test_a_loop_is_a_normalised_shape_with_no_coordinates(analysis_db, client_factory):
    # 2000 m east-west by 1000 m north-south: 6 km, 2000 GPS seconds.
    track = rectangle_loop(2000, 1000)
    assert len(track) > 1500
    add_route_run(analysis_db, 5, START_LOCAL, track)

    body = get_detail(client_factory, 5)

    assert_no_coordinates(body, track)
    route = body["route"]
    assert set(route) == {"x", "y", "start_index", "finish_index", "metres_per_unit", "method"}
    xs, ys = route["x"], route["y"]
    assert len(xs) == len(ys) <= 500
    assert all(0.0 <= v <= 1.0 for v in xs + ys)
    # The longer side spans [0, 1]; the shorter keeps the 2:1 aspect ratio.
    assert (min(xs), max(xs)) == pytest.approx((0.0, 1.0))
    assert max(ys) - min(ys) == pytest.approx(0.5, abs=0.005)
    assert route["metres_per_unit"] == pytest.approx(2000, rel=0.005)
    # y grows southwards (screen order): the start is the south-west corner.
    s, f = route["start_index"], route["finish_index"]
    assert (s, f) == (0, len(xs) - 1)
    assert (xs[s], ys[s]) == pytest.approx((0.0, max(ys)), abs=0.005)
    assert (xs[f], ys[f]) == pytest.approx((0.0, max(ys)), abs=0.005)
    # Simplification keeps the corners.
    for cx, cy in [(1.0, max(ys)), (1.0, min(ys)), (0.0, min(ys))]:
        assert any(math.hypot(x - cx, y - cy) < 0.005 for x, y in zip(xs, ys, strict=True)), (
            cx,
            cy,
        )
    assert route["method"]["params"]["max_points"] == 500
    # Straight sides need no more than their corners: points closer than the
    # tolerance (0.5 m) to the chord are dropped, not kept up to the cap.
    assert len(xs) <= 10
    assert route["method"]["params"]["tolerance_m"] == 0.5
    assert body["route_unavailable"] is None


def test_a_winding_route_is_simplified_to_500_points(analysis_db, client_factory):
    # 3000 m east in a 2 m zigzag: every one of the 3001 GPS seconds is a
    # corner 2 m off its neighbours' chord, so only the cap stops the simplification.
    track: list[LatLon] = [at(1.0 * i, 2.0 * (i % 2)) for i in range(3001)]
    add_route_run(analysis_db, 6, START_LOCAL, track, speed=2.2)

    body = get_detail(client_factory, 6)

    assert_no_coordinates(body, track)
    route = body["route"]
    xs, ys = route["x"], route["y"]
    assert len(xs) == len(ys) == 500
    assert (min(xs), max(xs)) == pytest.approx((0.0, 1.0))
    assert all(0.0 <= y <= 2.0 / 3000 + 1e-6 for y in ys)
    assert route["metres_per_unit"] == pytest.approx(3000, rel=0.005)
    # Start west, finish east.
    assert xs[route["start_index"]] == pytest.approx(0.0)
    assert xs[route["finish_index"]] == pytest.approx(1.0)


def test_seconds_without_a_fix_are_left_out(analysis_db, client_factory):
    # No fix for the first 100 and last 50 seconds; in between an out-and-back
    # 900 m north and back. Start and finish are the first and last fixes.
    out = [at(0, 3 * i) for i in range(300)]
    track: list[LatLon] = [None] * 100 + out + [at(0, 900)] + out[::-1] + [None] * 50
    add_route_run(analysis_db, 8, START_LOCAL, track)

    body = get_detail(client_factory, 8)

    assert_no_coordinates(body, track)
    route = body["route"]
    xs, ys = route["x"], route["y"]
    assert all(x == pytest.approx(0.0) for x in xs)
    assert (min(ys), max(ys)) == pytest.approx((0.0, 1.0))
    assert route["metres_per_unit"] == pytest.approx(900, rel=0.005)
    assert ys[route["start_index"]] == pytest.approx(1.0)
    assert ys[route["finish_index"]] == pytest.approx(1.0)
    # The turnaround is kept.
    assert min(ys) == pytest.approx(0.0)


def test_a_run_without_gps_has_no_route_and_says_why(analysis_db, client_factory):
    # Records with HR and cadence but no lat/lon, as on a treadmill.
    add_route_run(analysis_db, 9, START_LOCAL, [None] * 1200, "treadmill_running")

    body = get_detail(client_factory, 9)

    assert body["route"] is None
    assert body["route_unavailable"] == "没有 GPS 记录（跑步机或室内活动）"


def test_an_activity_without_records_has_no_route(analysis_db, client_factory):
    insert_activity(analysis_db, 10, START_LOCAL, "treadmill_running", distance_m=6000)

    body = get_detail(client_factory, 10)

    assert body["route"] is None
    assert body["route_unavailable"] == "没有 GPS 记录（跑步机或室内活动）"


def test_a_single_fix_is_too_little_for_a_shape(analysis_db, client_factory):
    add_route_run(analysis_db, 11, START_LOCAL, [None] * 600 + [at(0, 0)] * 600)

    body = get_detail(client_factory, 11)

    assert body["route"] is None
    assert body["route_unavailable"] == "GPS 定位点不足，画不出形状"
