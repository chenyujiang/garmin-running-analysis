//! Seam 1 for the Garmin account export: an export zip in, raw archive and
//! analysis database out, via `runsync import-export <zip>` (and `rebuild`).
//! The package is the synthetic one from `common::export`.

mod common;

use std::path::{Path, PathBuf};

use chrono::NaiveDate;
use common::export::{ExportZip, activity, day, standard_package, uds_row, utc, vo2max_row};
use common::{runsync, stderr, stdout};
use rusqlite::Connection;
use tempfile::TempDir;

fn open_db(data_dir: &Path) -> Connection {
    Connection::open(data_dir.join("running.sqlite")).unwrap()
}

/// An empty data directory and, outside it, the standard package as
/// `export.zip`.
fn setup() -> (TempDir, TempDir, PathBuf) {
    let data = TempDir::new().unwrap();
    std::fs::copy(
        common::fixture_archive().join("config.toml"),
        data.path().join("config.toml"),
    )
    .unwrap();
    let downloads = TempDir::new().unwrap();
    let zip = downloads.path().join("export.zip");
    standard_package().write(&zip);
    (data, downloads, zip)
}

fn import(data_dir: &Path, zip: &Path) -> String {
    let out = runsync(data_dir, &["import-export", zip.to_str().unwrap()]);
    assert!(
        out.status.success(),
        "import-export failed: {}",
        stderr(&out)
    );
    stdout(&out)
}

#[test]
fn import_archives_the_package_under_its_export_date_and_loads_activities_in_si() {
    let (data, _downloads, zip) = setup();

    import(data.path(), &zip);

    let archived = data.path().join("raw/export/2026-10-28/export.zip");
    assert_eq!(
        std::fs::read(&archived).unwrap(),
        std::fs::read(&zip).unwrap()
    );
    let db = open_db(data.path());
    let row = db
        .query_row(
            "SELECT activity_type, activity_name, start_time_utc, start_time_local, time_zone,
                    distance_m, duration_s, moving_duration_s, elapsed_duration_s,
                    avg_speed_mps, max_speed_mps, avg_hr_bpm, max_hr_bpm,
                    elevation_gain_m, elevation_loss_m, calories_kcal
             FROM activities WHERE activity_id = 9001",
            [],
            |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, String>(3)?,
                    r.get::<_, Option<String>>(4)?,
                    (5..=15)
                        .map(|i| r.get::<_, f64>(i))
                        .collect::<Result<Vec<_>, _>>()?,
                ))
            },
        )
        .unwrap();
    assert_eq!(row.0, "running");
    assert_eq!(row.1, "Synthetic running 9001");
    assert_eq!(row.2, "2026-10-20T06:00:00Z");
    assert_eq!(row.3, "2026-10-20T19:00:00");
    assert_eq!(row.4, None);
    let expected = [
        10_000.0, 3000.0, 2970.0, 3060.0, 3.333_333, 4.5, 151.0, 176.0, 42.5, 41.0, 600.0,
    ];
    for (got, want) in row.5.iter().zip(expected) {
        assert!((got - want).abs() < 1e-3, "got {:?}", row.5);
    }
    let types: Vec<(i64, String)> = db
        .prepare("SELECT activity_id, activity_type FROM activities ORDER BY activity_id")
        .unwrap()
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
        .unwrap()
        .collect::<Result<_, _>>()
        .unwrap();
    assert_eq!(
        types,
        [
            (9001, "running".to_owned()),
            (9002, "strength_training".to_owned()),
            (9003, "running".to_owned())
        ]
    );
}

#[test]
fn uds_day_rows_become_daily_wellness_rows() {
    let (data, _downloads, zip) = setup();

    let out = import(data.path(), &zip);

    let db = open_db(data.path());
    assert_eq!(count(&db, "SELECT count(*) FROM daily_wellness"), 28);
    let day = |date: &str| -> Vec<Option<f64>> {
        db.query_row(
            "SELECT resting_hr_bpm, min_hr_bpm, max_hr_bpm, steps, steps_distance_m,
                    calories_total_kcal, calories_active_kcal, calories_resting_kcal,
                    intensity_moderate_min, intensity_vigorous_min, stress_avg,
                    body_battery_min, body_battery_max, respiration_avg_brpm
             FROM daily_wellness WHERE calendar_date = ?1",
            [date],
            |r| (0..14).map(|i| r.get::<_, Option<f64>>(i)).collect(),
        )
        .unwrap()
    };
    let full = [
        46.0, 47.0, 172.0, 9100.0, 7320.0, 2210.0, 560.0, 1650.0, 14.0, 33.0, 25.0, 22.0, 87.0,
        15.0,
    ];
    assert_eq!(day("2026-10-20"), full.map(Some));
    // No resting heart rate in the row, and stress -1 ("no data"): NULL.
    let sparse = day("2026-10-21");
    assert_eq!(sparse[0], None);
    assert_eq!(sparse[10], None);
    assert_eq!(sparse[1], Some(47.0));
    assert!(
        out.contains("daily summaries: 28 days (2026-10-01..2026-10-28)"),
        "{out}"
    );
}

/// date, vo2max, race_5k_s, race_marathon_s, training_status, acute_load.
type MetricsRow = (
    String,
    Option<f64>,
    Option<f64>,
    Option<f64>,
    Option<String>,
    Option<f64>,
);

#[test]
fn metrics_files_fill_garmin_metrics_with_the_latest_value_per_day() {
    let (data, _downloads, zip) = setup();

    let out = import(data.path(), &zip);

    let db = open_db(data.path());
    let rows: Vec<MetricsRow> = db
        .prepare(
            "SELECT date, vo2max, race_5k_s, race_marathon_s, training_status, acute_load
             FROM garmin_metrics ORDER BY date",
        )
        .unwrap()
        .query_map([], |r| {
            Ok((
                r.get(0)?,
                r.get(1)?,
                r.get(2)?,
                r.get(3)?,
                r.get(4)?,
                r.get(5)?,
            ))
        })
        .unwrap()
        .collect::<Result<_, _>>()
        .unwrap();
    assert_eq!(
        rows,
        [
            ("2026-10-01".to_owned(), Some(54.0), None, None, None, None),
            (
                "2026-10-20".to_owned(),
                // The later of two RUNNING updates; the CYCLING value is ignored.
                Some(56.0),
                // The prediction with the later timestamp.
                Some(1150.0),
                Some(13_400.0),
                Some("PRODUCTIVE".to_owned()),
                None
            ),
        ]
    );
    assert!(
        out.contains("Garmin metrics: 2 days (2026-10-01..2026-10-20)"),
        "{out}"
    );
}

#[test]
fn data_already_archived_from_the_api_takes_precedence() {
    // The fixture archive has API activity 1001 (start 2026-10-07T22:08:46Z)
    // and API daily summaries for 2026-10-07 and 2026-10-08.
    let data = common::data_dir_from_fixture();
    let vo2max = data.path().join("raw/garminconnect/vo2max");
    std::fs::create_dir_all(&vo2max).unwrap();
    std::fs::write(
        vo2max.join("2026-10-04.json"),
        r#"[{"generic":{"calendarDate":"2026-10-04","vo2MaxPreciseValue":57.3}}]"#,
    )
    .unwrap();
    assert!(runsync(data.path(), &["rebuild"]).status.success());
    let downloads = TempDir::new().unwrap();
    let zip = downloads.path().join("export.zip");
    let d = |n| day(2026, 10, n);
    ExportZip::new(d(28))
        .activities(
            1,
            vec![
                activity(1001, "running", utc(2026, 10, 7, 22, 8), 5.0, 1500.0),
                activity(9001, "running", utc(2026, 10, 20, 6, 0), 10.0, 3000.0),
            ],
        )
        .uds(
            "x",
            vec![uds_row(d(7), Some(60), 30), uds_row(d(9), Some(61), 30)],
        )
        .metrics(
            "MetricsMaxMetData",
            "x",
            vec![
                vo2max_row(d(4), "RUNNING", "2026-10-04T08:00:00.0", 50.0),
                vo2max_row(d(11), "RUNNING", "2026-10-11T08:00:00.0", 51.0),
            ],
        )
        .write(&zip);

    let out = import(data.path(), &zip);

    let db = open_db(data.path());
    let names: Vec<String> = db
        .prepare("SELECT activity_name FROM activities ORDER BY activity_id")
        .unwrap()
        .query_map([], |r| r.get(0))
        .unwrap()
        .collect::<Result<_, _>>()
        .unwrap();
    assert_eq!(
        names,
        [
            "Fixture easy run",
            "Fixture strength session without HR",
            "Synthetic running 9001"
        ]
    );
    let resting: Vec<(String, f64)> = db
        .prepare("SELECT calendar_date, resting_hr_bpm FROM daily_wellness ORDER BY 1")
        .unwrap()
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
        .unwrap()
        .collect::<Result<_, _>>()
        .unwrap();
    assert_eq!(
        resting,
        [
            ("2026-10-07".to_owned(), 53.0),
            ("2026-10-09".to_owned(), 61.0)
        ]
    );
    let vo2: Vec<(String, f64)> = db
        .prepare("SELECT date, vo2max FROM garmin_metrics ORDER BY date")
        .unwrap()
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
        .unwrap()
        .collect::<Result<_, _>>()
        .unwrap();
    assert_eq!(
        vo2,
        [
            ("2026-10-04".to_owned(), 57.3),
            ("2026-10-11".to_owned(), 51.0)
        ]
    );
    assert!(
        out.contains(
            "kept from the API: 1 activities, 0 activity FITs, 1 daily summaries, \
             1 metric values"
        ),
        "{out}"
    );
}

/// A package exported on `exported` with activity 9001 of `km` and a resting
/// heart rate of `resting` on 2026-10-20.
fn small_package(exported: NaiveDate, km: f64, resting: i64) -> ExportZip {
    ExportZip::new(exported)
        .activities(
            1,
            vec![activity(
                9001,
                "running",
                utc(2026, 10, 20, 6, 0),
                km,
                3000.0,
            )],
        )
        .uds("x", vec![uds_row(day(2026, 10, 20), Some(resting), 25)])
}

fn distance_and_resting(data_dir: &Path) -> (f64, f64) {
    let db = open_db(data_dir);
    (
        db.query_row("SELECT distance_m FROM activities", [], |r| r.get(0))
            .unwrap(),
        db.query_row("SELECT resting_hr_bpm FROM daily_wellness", [], |r| {
            r.get(0)
        })
        .unwrap(),
    )
}

#[test]
fn a_newer_package_overrides_an_older_one_whatever_the_import_order() {
    let (data, downloads, _) = setup();
    let older = downloads.path().join("older.zip");
    let newer = downloads.path().join("newer.zip");
    small_package(day(2026, 9, 1), 10.0, 50).write(&older);
    small_package(day(2026, 10, 28), 12.0, 46).write(&newer);

    import(data.path(), &older);
    assert_eq!(distance_and_resting(data.path()), (10_000.0, 50.0));
    import(data.path(), &newer);
    assert_eq!(distance_and_resting(data.path()), (12_000.0, 46.0));
    import(data.path(), &older);
    assert_eq!(distance_and_resting(data.path()), (12_000.0, 46.0));

    assert!(
        data.path()
            .join("raw/export/2026-09-01/older.zip")
            .is_file()
    );
    assert!(
        data.path()
            .join("raw/export/2026-10-28/newer.zip")
            .is_file()
    );
}

#[test]
fn importing_the_same_package_again_changes_nothing() {
    let (data, _downloads, zip) = setup();
    import(data.path(), &zip);
    let tables = [
        "activities",
        "records",
        "laps",
        "daily_wellness",
        "garmin_metrics",
    ];
    let counts = |db: &Connection| -> Vec<i64> {
        tables
            .iter()
            .map(|t| count(db, &format!("SELECT count(*) FROM {t}")))
            .collect()
    };
    let before = counts(&open_db(data.path()));

    import(data.path(), &zip);
    // Importing the archived copy itself works too.
    import(
        data.path(),
        &data.path().join("raw/export/2026-10-28/export.zip"),
    );

    assert_eq!(counts(&open_db(data.path())), before);
    assert_eq!(before, [3, 4, 2, 28, 2]);
    let archived: Vec<_> = std::fs::read_dir(data.path().join("raw/export/2026-10-28"))
        .unwrap()
        .map(|e| e.unwrap().file_name())
        .collect();
    assert_eq!(archived, ["export.zip"]);
}

/// Every row of the analysis tables, as text.
fn dump(data_dir: &Path) -> Vec<String> {
    let db = open_db(data_dir);
    let mut rows = Vec::new();
    for table in [
        "activities",
        "records",
        "laps",
        "daily_wellness",
        "garmin_metrics",
    ] {
        let mut stmt = db
            .prepare(&format!("SELECT * FROM {table} ORDER BY 1, 2"))
            .unwrap();
        let n = stmt.column_count();
        let table_rows: Vec<String> = stmt
            .query_map([], |r| {
                let values: Vec<String> = (0..n)
                    .map(|i| format!("{:?}", r.get::<_, rusqlite::types::Value>(i).unwrap()))
                    .collect();
                Ok(format!("{table}: {}", values.join(", ")))
            })
            .unwrap()
            .collect::<Result<_, _>>()
            .unwrap();
        rows.extend(table_rows);
    }
    rows
}

#[test]
fn rebuild_loads_the_archived_packages_to_the_same_database() {
    let data = common::data_dir_from_fixture();
    let downloads = TempDir::new().unwrap();
    let older = downloads.path().join("older.zip");
    small_package(day(2026, 9, 1), 10.0, 50).write(&older);
    let zip = downloads.path().join("export.zip");
    standard_package().write(&zip);
    assert!(runsync(data.path(), &["rebuild"]).status.success());
    import(data.path(), &zip);
    import(data.path(), &older);
    let imported = dump(data.path());

    let out = runsync(data.path(), &["rebuild"]);

    assert!(out.status.success(), "{}", stderr(&out));
    assert_eq!(dump(data.path()), imported);
    assert!(imported.len() > 40, "{imported:?}");
    assert!(
        stdout(&out).contains("2 export packages"),
        "{}",
        stdout(&out)
    );
}

#[test]
fn entries_named_outside_the_package_are_never_written() {
    let (data, downloads, _) = setup();
    let zip = downloads.path().join("hostile.zip");
    small_package(day(2026, 10, 28), 10.0, 50)
        .entry("../evil.txt", "x")
        .entry("../../evil.txt", "x")
        .entry(
            "DI_CONNECT/DI-Connect-Fitness/../../../evil_summarizedActivities.json",
            "[]",
        )
        .write(&zip);

    import(data.path(), &zip);

    let mut files = Vec::new();
    collect_files(data.path(), data.path(), &mut files);
    files.sort();
    assert_eq!(
        files,
        [
            "config.toml",
            "raw/export/2026-10-28/hostile.zip",
            "running.sqlite"
        ]
    );
    let mut around: Vec<_> = std::fs::read_dir(downloads.path())
        .unwrap()
        .map(|e| e.unwrap().file_name())
        .collect();
    around.sort();
    assert_eq!(around, ["export.zip", "hostile.zip"]);
    assert_eq!(distance_and_resting(data.path()), (10_000.0, 50.0));
}

/// Relative paths of the files under `dir`, without SQLite side files.
fn collect_files(root: &Path, dir: &Path, out: &mut Vec<String>) {
    for entry in std::fs::read_dir(dir).unwrap() {
        let path = entry.unwrap().path();
        if path.is_dir() {
            collect_files(root, &path, out);
        } else {
            let rel = path.strip_prefix(root).unwrap().to_string_lossy();
            let rel = rel.replace('\\', "/");
            if !rel.ends_with("-wal") && !rel.ends_with("-shm") {
                out.push(rel);
            }
        }
    }
}

fn count(db: &Connection, sql: &str) -> i64 {
    db.query_row(sql, [], |r| r.get(0)).unwrap()
}

#[test]
fn activity_fits_are_matched_by_start_time_and_the_rest_counted() {
    let (data, _downloads, zip) = setup();

    let out = import(data.path(), &zip);

    let db = open_db(data.path());
    let per_activity: Vec<(i64, i64)> = db
        .prepare("SELECT activity_id, count(*) FROM records GROUP BY activity_id")
        .unwrap()
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
        .unwrap()
        .collect::<Result<_, _>>()
        .unwrap();
    assert_eq!(per_activity, [(9001, 2), (9003, 2)]);
    let (start, distance): (String, f64) = db
        .query_row(
            "SELECT start_time_utc, distance_m FROM laps WHERE activity_id = 9001",
            [],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .unwrap();
    assert_eq!(start, "2026-10-20T06:00:00Z");
    assert_eq!(distance, 2.5);
    assert_eq!(count(&db, "SELECT count(*) FROM laps"), 2);
    assert!(
        out.contains(
            "FIT files: 2 activities loaded, 1 matching no activity, \
             1 not an activity (skipped), 1 failed to parse"
        ),
        "{out}"
    );
}
