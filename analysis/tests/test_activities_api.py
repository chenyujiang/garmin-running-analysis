"""Seam 3: the activity list, GET /api/activities.

Newest first, filtered by type (running types by default, or all) and by
minimum distance, paged. Running pace counts running seconds only (walking
left out), as everywhere else in the dashboard.
"""

import pytest
from synthetic import add_run, insert_activity, run, walk


def get_activities(client_factory, **params) -> dict:
    r = client_factory().get("/api/activities", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def ids(body: dict) -> list[int]:
    return [a["activity_id"] for a in body["activities"]]


def test_activities_are_listed_newest_first(analysis_db, client_factory):
    insert_activity(analysis_db, 1, "2026-10-20T07:00:00", distance_m=5000, duration_s=1500)
    insert_activity(
        analysis_db,
        2,
        "2026-10-22T18:30:00",
        "trail_running",
        distance_m=8000,
        duration_s=3000,
        activity_name="周四越野",
        avg_hr_bpm=151.0,
    )
    insert_activity(analysis_db, 3, "2026-10-21T07:00:00", distance_m=6000, duration_s=1800)

    body = get_activities(client_factory)

    assert body["has_data"] is True
    assert body["total"] == 3
    assert ids(body) == [2, 3, 1]
    row = body["activities"][0]
    assert row["activity_type"] == "trail_running"
    assert row["activity_name"] == "周四越野"
    assert row["start_time_local"] == "2026-10-22T18:30:00"
    assert row["distance_m"] == pytest.approx(8000.0)
    assert row["duration_s"] == pytest.approx(3000.0)
    assert row["avg_hr_bpm"] == pytest.approx(151.0)


def test_running_pace_leaves_the_walk_out(analysis_db, client_factory):
    # 20 min at 5:33/km, then a 5 min cool-down walk. Garmin's overall pace is
    # 373.1 s/km; the running pace stays ~333 s/km (same case as the weekly volume).
    add_run(analysis_db, 1, "2026-10-27T07:00:00", [run(1200), walk(300)])
    add_run(analysis_db, 2, "2026-10-28T07:00:00", [run(600)], "cycling")
    # A running activity without records: Garmin's totals, 6000 m in 1800 s.
    insert_activity(analysis_db, 3, "2026-10-29T07:00:00", distance_m=6000, duration_s=1800)

    rows = {a["activity_id"]: a for a in get_activities(client_factory, type="all")["activities"]}

    assert rows[1]["running_pace_s_per_km"] == pytest.approx(333.3, abs=1.0)
    assert rows[2]["running_pace_s_per_km"] is None
    assert rows[3]["running_pace_s_per_km"] == pytest.approx(300.0)


def test_running_types_by_default_and_every_type_on_request(analysis_db, client_factory):
    insert_activity(analysis_db, 1, "2026-10-20T07:00:00", "running", distance_m=5000)
    insert_activity(analysis_db, 2, "2026-10-21T07:00:00", "cycling", distance_m=20000)
    insert_activity(analysis_db, 3, "2026-10-22T07:00:00", "treadmill_running", distance_m=4000)
    insert_activity(analysis_db, 4, "2026-10-23T07:00:00", "strength_training")

    running = get_activities(client_factory)
    every = get_activities(client_factory, type="all")

    assert ids(running) == [3, 1]
    assert running["total"] == 2
    assert running["type_filter"] == "running"
    assert ids(every) == [4, 3, 2, 1]
    assert every["total"] == 4


def test_an_unknown_type_filter_is_rejected(analysis_db, client_factory):
    r = client_factory().get("/api/activities", params={"type": "cycling"})

    assert r.status_code == 422


def test_minimum_distance_in_km(analysis_db, client_factory):
    insert_activity(analysis_db, 1, "2026-10-20T07:00:00", distance_m=9999)
    insert_activity(analysis_db, 2, "2026-10-21T07:00:00", distance_m=10000)
    insert_activity(analysis_db, 3, "2026-10-22T07:00:00", distance_m=21100)
    insert_activity(analysis_db, 4, "2026-10-23T07:00:00")  # no distance

    body = get_activities(client_factory, min_km=10)

    assert ids(body) == [3, 2]
    assert body["total"] == 2
    assert body["min_distance_m"] == pytest.approx(10000.0)
    assert ids(get_activities(client_factory)) == [4, 3, 2, 1]


def test_pages_and_total(analysis_db, client_factory):
    for i in range(1, 8):
        insert_activity(analysis_db, i, f"2026-10-{10 + i}T07:00:00", distance_m=5000)

    first = get_activities(client_factory, page_size=3)
    last = get_activities(client_factory, page_size=3, page=3)
    beyond = get_activities(client_factory, page_size=3, page=4)

    assert ids(first) == [7, 6, 5]
    assert first["total"] == 7
    assert first["page"] == 1
    assert first["page_size"] == 3
    assert ids(last) == [1]
    assert last["total"] == 7
    assert ids(beyond) == []
    assert get_activities(client_factory)["page_size"] == 50


@pytest.mark.parametrize("params", [{"page_size": 0}, {"page_size": 201}, {"page": 0}])
def test_page_size_out_of_range_is_rejected(analysis_db, client_factory, params):
    r = client_factory().get("/api/activities", params=params)

    assert r.status_code == 422


def test_page_size_200_is_allowed(analysis_db, client_factory):
    assert get_activities(client_factory, page_size=200)["page_size"] == 200


def test_no_database_means_no_activities(data_dir, client_factory):
    body = get_activities(client_factory)

    assert body["has_data"] is False
    assert body["total"] == 0
    assert body["activities"] == []
    assert body["method"]["params"]["cadence_spm"] == 140.0
    assert body["method"]["params"]["max_page_size"] == 200


def test_filters_that_match_nothing_still_report_data(analysis_db, client_factory):
    insert_activity(analysis_db, 1, "2026-10-20T07:00:00", "cycling", distance_m=30000)

    body = get_activities(client_factory)

    assert body["has_data"] is True
    assert body["total"] == 0


def test_a_search_matches_part_of_the_name_ignoring_case(analysis_db, client_factory):
    insert_activity(
        analysis_db,
        1,
        "2026-10-17T08:00:00",
        distance_m=5000,
        duration_s=1300,
        activity_name="Morning Parkrun",
    )
    insert_activity(
        analysis_db,
        2,
        "2026-10-24T08:00:00",
        distance_m=5000,
        duration_s=1250,
        activity_name="parkrun PB",
    )
    insert_activity(
        analysis_db,
        3,
        "2026-10-25T07:00:00",
        distance_m=12000,
        duration_s=4000,
        activity_name="周日长距离",
    )
    insert_activity(
        analysis_db,
        4,
        "2026-10-26T07:00:00",
        distance_m=6000,
        duration_s=1800,
        activity_name="100% effort",
    )

    assert ids(get_activities(client_factory, q="PARKRUN")) == [2, 1]
    assert ids(get_activities(client_factory, q="长距离")) == [3]
    # % is a character to find, not a wildcard.
    assert ids(get_activities(client_factory, q="%")) == [4]
    body = get_activities(client_factory, q="  parkrun ")
    assert body["query"] == "parkrun"
    assert body["total"] == 2


def test_a_date_range_includes_both_ends(analysis_db, client_factory):
    for i, day in enumerate(["2026-09-30", "2026-10-01", "2026-10-15", "2026-10-31", "2026-11-01"]):
        insert_activity(analysis_db, i + 1, f"{day}T07:00:00", distance_m=5000, duration_s=1500)

    body = get_activities(client_factory, date_from="2026-10-01", date_to="2026-10-31")

    assert ids(body) == [4, 3, 2]
    assert (body["date_from"], body["date_to"]) == ("2026-10-01", "2026-10-31")
    assert ids(get_activities(client_factory, date_from="2026-10-31")) == [5, 4]
