//! Seam 1 for FIT files: synthetic FIT files in the raw archive, `runsync
//! rebuild`, then `records` and `laps` in the analysis database.

mod common;

use std::path::Path;

use common::fit::{
    ENUM, FitWriter, MESG_FILE_ID, MESG_LAP, MESG_PRIVATE, MESG_RECORD, SINT8, SINT32, UINT8,
    UINT16, UINT32, field, fit_time, semicircles,
};
use common::{data_dir_from_fixture, runsync, stderr, stdout};
use rusqlite::Connection;

/// 2026-10-07T22:08:46Z, the start of fixture activity 1001.
const START_1001: i64 = 1_791_410_926;

fn file_id(created: i64) -> Vec<common::fit::Field> {
    vec![
        field(0, ENUM, 4), // type = activity
        field(4, UINT32, fit_time(created)),
    ]
}

/// Five one-second records with every column filled, two laps, and a
/// private manufacturer message that must not reach the database.
fn full_run_fit() -> Vec<u8> {
    let mut w = FitWriter::new().message(MESG_FILE_ID, &file_id(START_1001));
    w = w.message(MESG_PRIVATE, &[field(0, UINT8, 7), field(1, UINT16, 1234)]);
    for i in 0..5i64 {
        w = w.message(
            MESG_RECORD,
            &[
                field(253, UINT32, fit_time(START_1001 + i)),
                // Synthetic position off the coast of nowhere (0°, 0°).
                field(0, SINT32, semicircles(0.0001 * i as f64)),
                field(1, SINT32, semicircles(0.0002 * i as f64)),
                field(2, UINT16, (10 + 500) * 5), // altitude 10 m
                field(3, UINT8, 140 + i),         // heart rate bpm
                field(4, UINT8, 85),              // single-foot cadence rpm
                field(5, UINT32, 250 * i),        // distance 2.5 m per s, in cm
                field(6, UINT16, 2500),           // speed 2.5 m/s, in mm/s
                field(7, UINT16, 300),            // power W
                field(13, SINT8, 21),             // temperature °C
            ],
        );
    }
    for (start, secs) in [(START_1001, 3i64), (START_1001 + 3, 2)] {
        w = w.message(
            MESG_LAP,
            &[
                field(253, UINT32, fit_time(start + secs)),
                field(2, UINT32, fit_time(start)),
                field(7, UINT32, secs * 1000), // total_elapsed_time, ms
                field(8, UINT32, secs * 1000), // total_timer_time, ms
                field(9, UINT32, secs * 250),  // total_distance, cm
                field(13, UINT16, 2500),       // avg_speed, mm/s
                field(14, UINT16, 2600),       // max_speed, mm/s
                field(15, UINT8, 142),         // avg_heart_rate
                field(16, UINT8, 144),         // max_heart_rate
                field(17, UINT8, 85),          // avg_cadence, single foot
                field(21, UINT16, 3),          // total_ascent m
                field(22, UINT16, 1),          // total_descent m
            ],
        );
    }
    w.finish()
}

fn fit_path(dir: &Path, activity_id: i64) -> std::path::PathBuf {
    dir.join(format!("raw/personal_api/activities/{activity_id}.fit"))
}

fn rebuild_ok(dir: &Path) -> String {
    let out = runsync(dir, &["rebuild"]);
    assert!(out.status.success(), "rebuild failed: {}", stderr(&out));
    stdout(&out)
}

fn db(dir: &Path) -> Connection {
    Connection::open(dir.join("running.sqlite")).unwrap()
}

fn count(conn: &Connection, sql: &str) -> i64 {
    conn.query_row(sql, [], |r| r.get(0)).unwrap()
}

#[test]
fn rebuild_loads_one_record_row_per_fit_record() {
    let dir = data_dir_from_fixture();
    std::fs::write(fit_path(dir.path(), 1001), full_run_fit()).unwrap();

    rebuild_ok(dir.path());

    let conn = db(dir.path());
    assert_eq!(
        count(
            &conn,
            "SELECT count(*) FROM records WHERE activity_id = 1001"
        ),
        5
    );
}

#[test]
fn rebuild_stores_records_in_si_units_with_utc_timestamps() {
    let dir = data_dir_from_fixture();
    std::fs::write(fit_path(dir.path(), 1001), full_run_fit()).unwrap();
    rebuild_ok(dir.path());

    let row = db(dir.path())
        .query_row(
            "SELECT timestamp, heart_rate, speed, cadence, altitude, distance, power,
                    temperature, lat, lon
             FROM records WHERE activity_id = 1001 ORDER BY timestamp DESC LIMIT 1",
            [],
            |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    [
                        r.get::<_, f64>(1)?,
                        r.get::<_, f64>(2)?,
                        r.get::<_, f64>(3)?,
                        r.get::<_, f64>(4)?,
                        r.get::<_, f64>(5)?,
                        r.get::<_, f64>(6)?,
                        r.get::<_, f64>(7)?,
                    ],
                    r.get::<_, f64>(8)?,
                    r.get::<_, f64>(9)?,
                ))
            },
        )
        .unwrap();

    assert_eq!(row.0, "2026-10-07T22:08:50Z");
    // heart_rate bpm, speed m/s, cadence single-foot rpm as in the FIT,
    // altitude m, distance m, power W, temperature °C
    assert_eq!(row.1, [144.0, 2.5, 85.0, 10.0, 10.0, 300.0, 21.0]);
    // lat/lon in degrees, not semicircles
    assert!((row.2 - 0.0004).abs() < 1e-6, "lat not in degrees");
    assert!((row.3 - 0.0008).abs() < 1e-6, "lon not in degrees");
}

/// Three records with only a heart rate (no GPS, no speed, ...); the
/// last one's heart rate is the FIT invalid value. One lap.
fn sparse_run_fit(start: i64) -> Vec<u8> {
    let mut w = FitWriter::new().message(MESG_FILE_ID, &file_id(start));
    for (i, hr) in [(0i64, 120i64), (1, 121), (2, 0xFF)] {
        w = w.message(
            MESG_RECORD,
            &[field(253, UINT32, fit_time(start + i)), field(3, UINT8, hr)],
        );
    }
    w = w.message(
        MESG_LAP,
        &[
            field(253, UINT32, fit_time(start + 2)),
            field(2, UINT32, fit_time(start)),
        ],
    );
    w.finish()
}

#[test]
fn rebuild_leaves_missing_record_values_null() {
    let dir = data_dir_from_fixture();
    std::fs::write(fit_path(dir.path(), 1002), sparse_run_fit(START_1001)).unwrap();
    rebuild_ok(dir.path());

    let conn = db(dir.path());
    assert_eq!(
        count(
            &conn,
            "SELECT count(*) FROM records WHERE activity_id = 1002"
        ),
        3
    );
    assert_eq!(
        count(
            &conn,
            "SELECT count(*) FROM records WHERE activity_id = 1002
               AND speed IS NULL AND cadence IS NULL AND altitude IS NULL
               AND distance IS NULL AND lat IS NULL AND lon IS NULL
               AND power IS NULL AND temperature IS NULL"
        ),
        3
    );
    assert_eq!(
        count(
            &conn,
            "SELECT count(*) FROM records WHERE activity_id = 1002 AND heart_rate IS NULL"
        ),
        1
    );
}

#[test]
fn rebuild_stores_the_watch_laps_in_si_units() {
    let dir = data_dir_from_fixture();
    std::fs::write(fit_path(dir.path(), 1001), full_run_fit()).unwrap();
    rebuild_ok(dir.path());

    let conn = db(dir.path());
    assert_eq!(
        count(&conn, "SELECT count(*) FROM laps WHERE activity_id = 1001"),
        2
    );
    let lap = conn
        .query_row(
            "SELECT start_time_utc, end_time_utc, elapsed_duration_s, timer_duration_s,
                    distance_m, avg_speed_mps, max_speed_mps, avg_hr_bpm, max_hr_bpm,
                    avg_cadence, elevation_gain_m, elevation_loss_m
             FROM laps WHERE activity_id = 1001 AND lap_index = 1",
            [],
            |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    [
                        r.get::<_, f64>(2)?,
                        r.get::<_, f64>(3)?,
                        r.get::<_, f64>(4)?,
                        r.get::<_, f64>(5)?,
                        r.get::<_, f64>(6)?,
                        r.get::<_, f64>(7)?,
                        r.get::<_, f64>(8)?,
                        r.get::<_, f64>(9)?,
                        r.get::<_, f64>(10)?,
                        r.get::<_, f64>(11)?,
                    ],
                ))
            },
        )
        .unwrap();
    assert_eq!(lap.0, "2026-10-07T22:08:49Z");
    assert_eq!(lap.1, "2026-10-07T22:08:51Z");
    assert_eq!(
        lap.2,
        [2.0, 2.0, 5.0, 2.5, 2.6, 142.0, 144.0, 85.0, 3.0, 1.0]
    );
}

#[test]
fn rebuild_ignores_private_manufacturer_messages() {
    let dir = data_dir_from_fixture();
    std::fs::write(fit_path(dir.path(), 1001), full_run_fit()).unwrap();
    rebuild_ok(dir.path());

    let conn = db(dir.path());
    let unknown_tables = count(
        &conn,
        "SELECT count(*) FROM sqlite_master WHERE name LIKE 'unknown%'",
    );
    assert_eq!(unknown_tables, 0);
    // The private message sits before the records; it adds no rows.
    assert_eq!(count(&conn, "SELECT count(*) FROM records"), 5);
}

#[test]
fn rebuild_skips_unparseable_fit_files_and_keeps_the_rest() {
    let dir = data_dir_from_fixture();
    std::fs::write(fit_path(dir.path(), 1001), full_run_fit()).unwrap();
    // Not a FIT file at all.
    std::fs::write(fit_path(dir.path(), 1003), b"this is not a FIT file").unwrap();
    // fitparser issue #58: a developer field used before it is described.
    let issue_58 = FitWriter::new()
        .message(MESG_FILE_ID, &file_id(START_1001))
        .message_with_undescribed_dev_fields(
            MESG_RECORD,
            &[
                field(253, UINT32, fit_time(START_1001)),
                field(3, UINT8, 150),
            ],
            &[(0, 2, 0)],
        )
        .finish();
    std::fs::write(fit_path(dir.path(), 1004), issue_58).unwrap();
    // A sound file after the bad ones, so a bad file must not stop the loop.
    std::fs::write(fit_path(dir.path(), 1005), sparse_run_fit(START_1001)).unwrap();

    let out = rebuild_ok(dir.path());
    assert!(out.contains("2 FIT files"), "{out}");
    assert!(out.contains("2 files skipped"), "{out}");

    let conn = db(dir.path());
    assert_eq!(
        count(&conn, "SELECT count(DISTINCT activity_id) FROM records"),
        2
    );
    assert_eq!(
        count(
            &conn,
            "SELECT count(*) FROM records WHERE activity_id IN (1003, 1004)"
        ),
        0
    );
    // The bad files stay in the raw archive.
    assert!(fit_path(dir.path(), 1003).exists());
    assert!(fit_path(dir.path(), 1004).exists());
}
