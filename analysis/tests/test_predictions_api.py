"""Seam 3: race predictions (GET /api/predictions) and the race list (GET /api/races).

TODAY = 2026-10-28, so the 6-month window starts 2026-04-28. Expected times
come from formulas.md (VDOT, Riegel and Vickers vectors).
"""

from datetime import date, timedelta

import pytest
from synthetic import insert_activity

TODAY = "2026-10-28"
HEADER = "date,activity_id,distance_m,time_s,all_out,note\n"
MILE_M = 1609.344


def hms(h: int, m: int, s: int) -> int:
    return h * 3600 + m * 60 + s


def write_races(data_dir, *rows: str) -> None:
    (data_dir / "races.csv").write_text(HEADER + "".join(r + "\n" for r in rows), encoding="utf-8")


def get(client_factory, path: str, today: str = TODAY) -> dict:
    r = client_factory().get(path, params={"today": today})
    assert r.status_code == 200
    return r.json()


def predictions(client_factory, today: str = TODAY) -> dict:
    return get(client_factory, "/api/predictions", today)


def row(body: dict, key: str) -> dict:
    [r] = [r for r in body["rows"] if r["key"] == key]
    return r


def weekly_miles(conn, miles: float, weeks: int = 8) -> None:
    """One run per week, without records, in the 8 weeks ending TODAY."""
    for i in range(weeks):
        day = date.fromisoformat(TODAY) - timedelta(days=7 * i)
        insert_activity(
            conn, 100 + i, f"{day}T07:00:00", distance_m=miles * MILE_M, duration_s=3600
        )


# --- races.csv problems -----------------------------------------------------


def test_a_missing_races_csv_says_so_and_gives_no_prediction(data_dir, client_factory):
    body = predictions(client_factory)

    assert body["races_error"]["kind"] == "missing"
    assert "races.csv" in body["races_error"]["message"]
    assert body["stale"] is True
    assert all(r["predicted_s"] is None for r in body["rows"])


def test_a_bad_number_in_races_csv_names_the_line(data_dir, client_factory):
    write_races(data_dir, "2026-10-01,,5000,20 min,yes,")

    body = predictions(client_factory)

    assert body["races_error"]["kind"] == "invalid"
    assert "第 2 行" in body["races_error"]["message"]
    assert "time_s" in body["races_error"]["message"]


def test_a_races_csv_with_wrong_columns_is_reported(data_dir, client_factory):
    (data_dir / "races.csv").write_text("date,distance,time\n2026-10-01,5000,1200\n", "utf-8")

    body = get(client_factory, "/api/races")

    assert body["races_error"]["kind"] == "invalid"
    assert "distance_m" in body["races_error"]["message"]
    assert body["races"] == []


# --- predictions ------------------------------------------------------------


def test_one_5k_gives_vdot_predictions_and_riegel_with_the_default_exponent(
    data_dir, analysis_db, client_factory
):
    write_races(data_dir, "2026-10-04,555,5000,1200,yes,parkrun")

    body = predictions(client_factory)

    assert body["stale"] is False
    assert body["races_error"] is None
    assert body["basis"]["date"] == "2026-10-04"
    assert body["basis"]["vdot"] == pytest.approx(49.806, abs=0.001)
    assert body["riegel_k"] == pytest.approx(1.06)
    assert body["riegel_k_source"] == "default"
    tenk = row(body, "10k")
    assert tenk["predicted_method"] == "vdot"
    assert tenk["riegel_s"] == pytest.approx(hms(0, 41, 42), abs=1)
    # VDOT 49.806 sits just under VDOT 50 (10K 41:20).
    assert hms(0, 41, 20) < tenk["vdot_s"] < hms(0, 41, 40)
    assert tenk["predicted_s"] == tenk["vdot_s"]
    assert row(body, "5k")["vdot_s"] == pytest.approx(1200, abs=0.01)


def test_the_marathon_uses_vickers_model_1_with_recent_weekly_volume(
    data_dir, analysis_db, client_factory
):
    write_races(data_dir, "2026-10-04,,5000,1200,yes,")
    weekly_miles(analysis_db, 30)

    body = predictions(client_factory)

    assert body["weekly_miles"] == pytest.approx(30, abs=0.01)
    assert body["weekly_km"] == pytest.approx(30 * 1.609344, abs=0.01)
    marathon = row(body, "marathon")
    assert marathon["predicted_method"] == "vickers_model1"
    assert marathon["predicted_s"] == pytest.approx(hms(3, 30, 55), abs=1)
    assert marathon["riegel_s"] == pytest.approx(hms(3, 11, 49), abs=1)


def test_two_races_fit_the_riegel_exponent_and_use_vickers_model_2(
    data_dir, analysis_db, client_factory
):
    write_races(data_dir, "2026-09-06,,10000,2520,yes,", "2026-10-11,,21097.5,5580,yes,")
    weekly_miles(analysis_db, 40)

    body = predictions(client_factory)

    assert body["riegel_k_source"] == "personal"
    assert body["riegel_k"] == pytest.approx(1.064777, abs=1e-5)
    marathon = row(body, "marathon")
    assert marathon["predicted_method"] == "vickers_model2"
    assert marathon["predicted_s"] == pytest.approx(hms(3, 25, 8), abs=1)


def test_the_basis_is_the_best_all_out_race_in_six_months(data_dir, client_factory):
    write_races(
        data_dir,
        "2026-10-04,,5000,1260,yes,",
        "2026-09-20,,5000,1200,yes,best",
        "2026-10-18,,5000,1100,no,paced someone, not all out",
        "2026-03-01,,5000,1000,yes,too old",
        "2026-11-01,,5000,1000,yes,after today",
    )

    body = predictions(client_factory)

    assert body["basis"]["date"] == "2026-09-20"
    assert body["basis"]["time_s"] == 1200
    assert body["last_race_date"] == "2026-10-04"


def test_no_all_out_race_in_six_months_is_stale_without_predictions(data_dir, client_factory):
    write_races(data_dir, "2026-04-27,,10000,2520,yes,", "2026-10-01,,5000,1000,no,")

    body = predictions(client_factory)

    assert body["stale"] is True
    assert body["races_error"] is None
    assert body["basis"] is None
    assert body["last_race_date"] == "2026-04-27"
    for r in body["rows"]:
        assert r["predicted_s"] is None
        assert r["vdot_s"] is None
        assert r["riegel_s"] is None


def test_a_race_exactly_six_months_ago_still_counts(data_dir, client_factory):
    write_races(data_dir, "2026-04-28,,10000,2520,yes,")

    assert predictions(client_factory)["stale"] is False


def test_garmin_column_is_empty_without_garmin_metrics(data_dir, analysis_db, client_factory):
    write_races(data_dir, "2026-10-04,,5000,1200,yes,")

    body = predictions(client_factory)

    assert body["garmin"] is None
    assert all(r["garmin_s"] is None for r in body["rows"])


def test_garmin_column_takes_the_latest_race_predictor_up_to_today(
    data_dir, analysis_db, client_factory
):
    analysis_db.execute(
        "CREATE TABLE IF NOT EXISTS garmin_metrics (date TEXT PRIMARY KEY, training_status TEXT,"
        " acute_load REAL, chronic_load REAL, acute_chronic_ratio REAL, vo2max REAL,"
        " race_5k_s REAL, race_10k_s REAL, race_half_marathon_s REAL, race_marathon_s REAL)"
    )
    analysis_db.executemany(
        "INSERT INTO garmin_metrics (date, vo2max, race_5k_s, race_10k_s,"
        " race_half_marathon_s, race_marathon_s) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("2026-10-18", 50, 1210, 2530, 5600, 11900),
            ("2026-10-25", 51, 1190, 2500, 5550, 11800),
            ("2026-10-26", 52, None, None, None, None),  # VO2max only
            ("2026-10-30", 53, 1000, 2000, 4000, 9000),  # after today
        ],
    )
    analysis_db.commit()
    write_races(data_dir, "2026-04-01,,5000,1200,yes,")  # stale: Garmin still shown

    body = predictions(client_factory)

    assert body["garmin"] == {"date": "2026-10-25"}
    assert row(body, "5k")["garmin_s"] == 1190
    assert row(body, "marathon")["garmin_s"] == 11800


def test_the_method_note_states_formulas_and_parameters(data_dir, client_factory):
    write_races(data_dir, "2026-10-04,,5000,1200,yes,")

    method = predictions(client_factory)["method"]

    assert method["params"]["window_months"] == 6
    assert method["params"]["riegel_k_default"] == 1.06
    assert method["params"]["volume_weeks"] == 8
    assert "Vickers" in method["description"]
    assert "VDOT" in method["description"]


# --- race list --------------------------------------------------------------


def test_the_race_list_is_newest_first_with_pace_and_vdot(data_dir, client_factory):
    write_races(
        data_dir,
        "2026-09-20,555,5000,1200,yes,parkrun",
        "2026-10-18,,10000,2520,no,",
        "2026-11-01,,5000,1000,yes,after today",
    )

    body = get(client_factory, "/api/races")

    assert body["races_error"] is None
    assert [r["date"] for r in body["races"]] == ["2026-10-18", "2026-09-20"]
    five = body["races"][1]
    assert five == {
        "date": "2026-09-20",
        "activity_id": 555,
        "distance_m": 5000.0,
        "time_s": 1200.0,
        "all_out": True,
        "note": "parkrun",
        "pace_s_per_km": pytest.approx(240.0),
        "vdot": pytest.approx(49.806, abs=0.001),
    }
    assert body["races"][0]["all_out"] is False
    assert body["races"][0]["activity_id"] is None


def test_all_out_accepts_common_spellings(data_dir, client_factory):
    write_races(
        data_dir,
        "2026-10-01,,5000,1200,TRUE,",
        "2026-10-02,,5000,1200,1,",
        "2026-10-03,,5000,1200,是,",
        "2026-10-04,,5000,1200,n,",
    )

    races = get(client_factory, "/api/races")["races"]

    assert [r["all_out"] for r in races] == [False, True, True, True]


def test_a_utf8_bom_from_excel_is_accepted(data_dir, client_factory):
    (data_dir / "races.csv").write_text(
        HEADER + "2026-10-01,,5000,1200,yes,奥克兰 parkrun\n", encoding="utf-8-sig"
    )

    races = get(client_factory, "/api/races")["races"]

    assert races[0]["note"] == "奥克兰 parkrun"
