//! Seam 1: raw archive in, analysis database out, via `runsync rebuild`.

mod common;

use common::{data_dir_from_fixture, runsync, stderr};
use rusqlite::{Connection, OptionalExtension};

fn open_db(data_dir: &std::path::Path) -> Connection {
    Connection::open(data_dir.join("running.sqlite")).unwrap()
}

#[test]
fn rebuild_loads_every_activity_detail_from_the_raw_archive() {
    let dir = data_dir_from_fixture();

    let out = runsync(dir.path(), &["rebuild"]);
    assert!(out.status.success(), "rebuild failed: {}", stderr(&out));

    let db = open_db(dir.path());
    let n: i64 = db
        .query_row("SELECT count(*) FROM activities", [], |r| r.get(0))
        .unwrap();
    assert_eq!(n, 2);
}

#[test]
fn rebuild_stores_si_units_and_both_start_timestamps() {
    let dir = data_dir_from_fixture();
    let out = runsync(dir.path(), &["rebuild"]);
    assert!(out.status.success(), "rebuild failed: {}", stderr(&out));

    let db = open_db(dir.path());
    let row = db
        .query_row(
            "SELECT activity_type, activity_name, start_time_utc, start_time_local, time_zone,
                    distance_m, duration_s, moving_duration_s, elapsed_duration_s,
                    avg_speed_mps, max_speed_mps, avg_hr_bpm, max_hr_bpm,
                    elevation_gain_m, elevation_loss_m
             FROM activities WHERE activity_id = 1001",
            [],
            |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, String>(3)?,
                    r.get::<_, String>(4)?,
                    [
                        r.get::<_, f64>(5)?,
                        r.get::<_, f64>(6)?,
                        r.get::<_, f64>(7)?,
                        r.get::<_, f64>(8)?,
                        r.get::<_, f64>(9)?,
                        r.get::<_, f64>(10)?,
                        r.get::<_, f64>(11)?,
                        r.get::<_, f64>(12)?,
                        r.get::<_, f64>(13)?,
                        r.get::<_, f64>(14)?,
                    ],
                ))
            },
        )
        .unwrap();

    assert_eq!(row.0, "running");
    assert_eq!(row.1, "Fixture easy run");
    assert_eq!(row.2, "2026-10-07T22:08:46Z");
    assert_eq!(row.3, "2026-10-08T11:08:46");
    assert_eq!(row.4, "Pacific/Auckland");
    assert_eq!(
        row.5,
        [
            10012.5, 3605.25, 3550.0, 3700.0, 2.777, 4.1, 146.0, 171.0, 87.0, 85.0
        ]
    );
}

#[test]
fn rebuild_leaves_missing_summary_fields_null() {
    let dir = data_dir_from_fixture();
    let out = runsync(dir.path(), &["rebuild"]);
    assert!(out.status.success(), "rebuild failed: {}", stderr(&out));

    let db = open_db(dir.path());
    let (distance, hr): (Option<f64>, Option<f64>) = db
        .query_row(
            "SELECT distance_m, avg_hr_bpm FROM activities WHERE activity_id = 1002",
            [],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .unwrap();
    assert_eq!((distance, hr), (None, None));
}

#[test]
fn rebuild_replaces_an_existing_analysis_database() {
    let dir = data_dir_from_fixture();
    assert!(runsync(dir.path(), &["rebuild"]).status.success());
    {
        let db = open_db(dir.path());
        db.execute(
            "INSERT INTO activities (activity_id, activity_type, start_time_utc, start_time_local)
             VALUES (9999, 'stale', '2020-01-01T00:00:00Z', '2020-01-01T00:00:00')",
            [],
        )
        .unwrap();
    }

    let out = runsync(dir.path(), &["rebuild"]);
    assert!(out.status.success(), "rebuild failed: {}", stderr(&out));

    let db = open_db(dir.path());
    let stale: Option<i64> = db
        .query_row(
            "SELECT activity_id FROM activities WHERE activity_id = 9999",
            [],
            |r| r.get(0),
        )
        .optional()
        .unwrap();
    assert_eq!(stale, None);
}

#[test]
fn rebuild_puts_the_analysis_database_in_wal_mode() {
    let dir = data_dir_from_fixture();
    assert!(runsync(dir.path(), &["rebuild"]).status.success());

    let db = open_db(dir.path());
    let mode: String = db
        .query_row("PRAGMA journal_mode", [], |r| r.get(0))
        .unwrap();
    assert_eq!(mode, "wal");
}

#[test]
fn rebuild_with_an_empty_archive_creates_an_empty_database() {
    let dir = tempfile::TempDir::new().unwrap();
    std::fs::copy(
        common::fixture_archive().join("config.toml"),
        dir.path().join("config.toml"),
    )
    .unwrap();

    let out = runsync(dir.path(), &["rebuild"]);
    assert!(out.status.success(), "rebuild failed: {}", stderr(&out));

    let n: i64 = open_db(dir.path())
        .query_row("SELECT count(*) FROM activities", [], |r| r.get(0))
        .unwrap();
    assert_eq!(n, 0);
}

#[test]
fn rebuild_skips_a_malformed_detail_file_and_keeps_going() {
    let dir = data_dir_from_fixture();
    std::fs::write(
        dir.path().join("raw/personal_api/activities/1000.json"),
        "{ not json",
    )
    .unwrap();

    let out = runsync(dir.path(), &["rebuild"]);
    assert!(out.status.success(), "rebuild failed: {}", stderr(&out));
    assert!(common::stdout(&out).contains("1 files skipped"));

    let n: i64 = open_db(dir.path())
        .query_row("SELECT count(*) FROM activities", [], |r| r.get(0))
        .unwrap();
    assert_eq!(n, 2);
}

#[test]
fn rebuild_reports_a_missing_data_directory() {
    let dir = tempfile::TempDir::new().unwrap();
    let missing = dir.path().join("nope");

    let out = runsync(&missing, &["rebuild"]);
    assert!(!out.status.success());
    let err = stderr(&out);
    assert!(err.contains("RUNNING_DATA_DIR"), "{err}");
    assert!(err.contains("nope"), "{err}");
}

#[test]
fn rebuild_reports_a_missing_config_file() {
    let dir = data_dir_from_fixture();
    std::fs::remove_file(dir.path().join("config.toml")).unwrap();

    let out = runsync(dir.path(), &["rebuild"]);
    assert!(!out.status.success());
    let err = stderr(&out);
    assert!(err.contains("config.toml"), "{err}");
    assert!(!dir.path().join("running.sqlite").exists());
}

#[test]
fn rebuild_loads_daily_summaries_and_skips_days_without_data() {
    let dir = data_dir_from_fixture();

    let out = runsync(dir.path(), &["rebuild"]);
    assert!(out.status.success(), "rebuild failed: {}", stderr(&out));
    assert!(
        common::stdout(&out).contains("1 daily summaries"),
        "{}",
        common::stdout(&out)
    );

    let db = open_db(dir.path());
    let n: i64 = db
        .query_row("SELECT count(*) FROM daily_wellness", [], |r| r.get(0))
        .unwrap();
    assert_eq!(n, 1);
    let row: (String, Option<i64>, i64, i64, f64, i64, i64, i64, f64) = db
        .query_row(
            "SELECT calendar_date, resting_hr_bpm, max_hr_bpm, steps, steps_distance_m,
                    calories_total_kcal, intensity_vigorous_min, body_battery_max,
                    respiration_avg_brpm
             FROM daily_wellness",
            [],
            |r| {
                Ok((
                    r.get(0)?,
                    r.get(1)?,
                    r.get(2)?,
                    r.get(3)?,
                    r.get(4)?,
                    r.get(5)?,
                    r.get(6)?,
                    r.get(7)?,
                    r.get(8)?,
                ))
            },
        )
        .unwrap();
    assert_eq!(
        row,
        (
            "2026-10-07".into(),
            // Garmin's resting heart rate is not loaded (see migration 0004).
            None,
            176,
            10234,
            8120.4,
            2264,
            34,
            91,
            15.0
        )
    );
}

#[test]
fn storing_the_same_day_twice_replaces_its_row() {
    let dir = tempfile::TempDir::new().unwrap();
    let conn = runsync::db::open(&dir.path().join("running.sqlite")).unwrap();
    let day =
        |max: i64| format!(r#"{{"calendarDate":"2026-10-07","heartRate":{{"maxValue":{max}}}}}"#);

    assert!(runsync::daily::store_day(&conn, &day(175)).unwrap());
    assert!(runsync::daily::store_day(&conn, &day(172)).unwrap());

    let rows: Vec<(String, i64)> = conn
        .prepare("SELECT calendar_date, max_hr_bpm FROM daily_wellness")
        .unwrap()
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
        .unwrap()
        .map(Result::unwrap)
        .collect();
    assert_eq!(rows, vec![("2026-10-07".to_string(), 172)]);
}
