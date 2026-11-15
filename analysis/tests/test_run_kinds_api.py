"""Seam 3: the run kind of each row in the activity list, GET /api/activities.

`run_kind` per running row: `race` (listed in races.csv), else `parkrun`
(Saturday morning 5 km, as on the predictions page), else the detail report's
training type, with interval and tempo runs grouped as `quality`. Null for
non-running activities and for runs the report cannot classify.
Config (conftest): LTHR 170, so Z3 starts at 153 bpm.
"""

from synthetic import insert_activity
from synthetic_aerobic import add_hr_run, steady

HEADER = "date,activity_id,distance_m,time_s,all_out,note\n"


def get_activities(client_factory, **params) -> dict:
    r = client_factory().get("/api/activities", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def kinds(body: dict) -> dict[int, str | None]:
    return {a["activity_id"]: a["run_kind"] for a in body["activities"]}


def intervals(reps: int) -> list:
    """Warm-up, `reps` x (2 min fast, 2 min slow), cool-down (as in the report tests)."""
    out = [steady(600, speed=3.0, hr=140.0)]
    for _ in range(reps):
        out += [steady(120, speed=4.0, hr=165.0), steady(120, speed=2.5, hr=150.0)]
    return [*out, steady(300, speed=3.0, hr=140.0)]


TEMPO = [steady(600, hr=140.0), steady(1200, hr=158.0), steady(300, hr=140.0)]


def test_each_run_gets_the_reports_training_type(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", [steady(1800, hr=140.0)])  # Tuesday
    add_hr_run(analysis_db, 2, "2026-10-21T07:00:00", [steady(3700, hr=140.0)])
    add_hr_run(analysis_db, 3, "2026-10-22T07:00:00", intervals(3))
    add_hr_run(analysis_db, 4, "2026-10-23T07:00:00", TEMPO)
    add_hr_run(analysis_db, 5, "2026-10-26T18:00:00", [steady(1800, hr=140.0)], "cycling")
    # No records: the report cannot classify it.
    insert_activity(analysis_db, 6, "2026-10-27T07:00:00", distance_m=6000, duration_s=1800)

    body = get_activities(client_factory, type="all")

    assert kinds(body) == {1: "easy", 2: "long", 3: "quality", 4: "quality", 5: None, 6: None}


def test_a_run_in_races_csv_is_a_race(data_dir, analysis_db, client_factory):
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", TEMPO)
    add_hr_run(analysis_db, 2, "2026-10-21T07:00:00", TEMPO)
    (data_dir / "races.csv").write_text(
        HEADER + "2026-10-20,1,6300,2100,yes,\n2026-10-21,,5000,1500,yes,\n", encoding="utf-8"
    )

    # Only the row naming the activity counts; a race without an id matches nothing.
    assert kinds(get_activities(client_factory)) == {1: "race", 2: "quality"}


FIVE_K = [steady(1000, speed=3.3, hr=158.0), steady(500, speed=3.3, hr=165.0)]  # 4950 m


def test_a_saturday_morning_5k_is_a_parkrun(data_dir, analysis_db, client_factory):
    add_hr_run(analysis_db, 1, "2026-10-24T09:00:00", FIVE_K)  # Saturday
    add_hr_run(analysis_db, 2, "2026-10-24T17:00:00", FIVE_K)  # Saturday evening
    add_hr_run(analysis_db, 3, "2026-10-25T09:00:00", FIVE_K)  # Sunday
    add_hr_run(analysis_db, 4, "2026-10-31T09:00:00", FIVE_K)  # Saturday, but in races.csv
    (data_dir / "races.csv").write_text(HEADER + "2026-10-31,4,5000,1500,yes,\n", "utf-8")

    body = kinds(get_activities(client_factory))

    assert body[1] == "parkrun"
    assert body[2] != "parkrun"
    assert body[3] != "parkrun"
    assert body[4] == "race"


def test_the_list_filters_by_run_kind(data_dir, analysis_db, client_factory):
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", TEMPO)
    add_hr_run(analysis_db, 2, "2026-10-21T07:00:00", [steady(1800, hr=140.0)])
    add_hr_run(analysis_db, 3, "2026-10-22T07:00:00", intervals(3))
    add_hr_run(analysis_db, 4, "2026-10-23T07:00:00", TEMPO)
    add_hr_run(analysis_db, 5, "2026-10-24T07:00:00", TEMPO, "cycling")
    (data_dir / "races.csv").write_text(HEADER + "2026-10-23,4,6300,2100,yes,\n", "utf-8")

    quality = get_activities(client_factory, kind="quality", type="all")
    second = get_activities(client_factory, kind="quality", page_size=1, page=2)

    assert kinds(quality) == {3: "quality", 1: "quality"}
    assert [a["activity_id"] for a in quality["activities"]] == [3, 1]
    assert quality["total"] == 2
    assert quality["kind"] == "quality"
    assert [a["activity_id"] for a in second["activities"]] == [1]
    assert second["total"] == 2
    assert kinds(get_activities(client_factory, kind="race")) == {4: "race"}
    assert get_activities(client_factory)["kind"] is None


def test_an_unknown_run_kind_is_rejected(analysis_db, client_factory):
    assert client_factory().get("/api/activities", params={"kind": "tempo"}).status_code == 422


def test_the_method_explains_the_run_kinds(data_dir, client_factory):
    method = get_activities(client_factory)["method"]

    assert method["params"]["run_kinds"] == [
        "race",
        "parkrun",
        "quality",
        "long",
        "easy",
        "mixed",
    ]
    assert "races.csv" in method["description"]
    assert "parkrun" in method["description"]


def test_a_broken_races_csv_leaves_the_training_types(data_dir, analysis_db, client_factory):
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", TEMPO)
    (data_dir / "races.csv").write_text("date,distance\n2026-10-20,5000\n", encoding="utf-8")

    assert kinds(get_activities(client_factory)) == {1: "quality"}


def test_a_non_running_activity_has_no_run_kind(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", TEMPO, "cycling")

    [ride] = get_activities(client_factory, type="all")["activities"]

    assert ride["activity_type"] == "cycling"
    assert ride["run_kind"] is None


def test_a_changed_run_is_classified_again(analysis_db, client_factory):
    add_hr_run(analysis_db, 1, "2026-10-20T07:00:00", [steady(1800, hr=140.0)])
    analysis_db.commit()
    assert kinds(get_activities(client_factory)) == {1: "easy"}

    # A later import rewrites the run's records: the whole run now in Z3.
    analysis_db.execute("UPDATE records SET heart_rate = 158 WHERE activity_id = 1")
    analysis_db.commit()

    assert kinds(get_activities(client_factory)) == {1: "quality"}
