//! Seam 2: the garminconnect metrics sync driven by an in-memory source.
//! Assertions are on the raw archive, the analysis database and what was
//! asked of the source.

mod common;

use std::path::{Path, PathBuf};

use chrono::NaiveDate;
use rusqlite::Connection;
use tempfile::TempDir;

use common::fake_metrics::FakeMetrics;
use common::fake_source::Failure;
use runsync::data_dir::DataDir;
use runsync::garmin_metrics::{MetricsSyncOptions, sync_garmin_metrics};
use runsync::source::{GarminMetric, MetricsSource, SourceError};

fn date(s: &str) -> NaiveDate {
    NaiveDate::parse_from_str(s, "%Y-%m-%d").unwrap()
}

/// 2026-10-30 is a Friday.
fn today() -> NaiveDate {
    date("2026-10-30")
}

fn options() -> MetricsSyncOptions {
    MetricsSyncOptions { today: today() }
}

fn empty_data_dir() -> (TempDir, DataDir) {
    let dir = TempDir::new().unwrap();
    std::fs::write(dir.path().join("config.toml"), "").unwrap();
    let data_dir = DataDir::open(dir.path().to_path_buf()).unwrap();
    (dir, data_dir)
}

fn raw(data_dir: &DataDir, metric: &str, day: &str) -> PathBuf {
    data_dir
        .garminconnect_dir()
        .join(metric)
        .join(format!("{day}.json"))
}

fn query<T: rusqlite::types::FromSql>(db: &Path, sql: &str) -> T {
    Connection::open(db)
        .unwrap()
        .query_row(sql, [], |r| r.get(0))
        .unwrap()
}

#[test]
fn a_sync_stores_todays_snapshot_of_all_three_metrics() {
    let (_dir, data_dir) = empty_data_dir();
    let mut source = FakeMetrics::new();

    let report = sync_garmin_metrics(&data_dir, &mut source, &options()).unwrap();

    assert!(report.stopped_by.is_none());
    for metric in ["training_status", "vo2max", "race_predictor"] {
        assert!(raw(&data_dir, metric, "2026-10-30").is_file(), "{metric}");
    }
    let db = data_dir.analysis_db_path();
    assert_eq!(query::<i64>(&db, "SELECT count(*) FROM garmin_metrics"), 1);
    assert_eq!(
        query::<String>(&db, "SELECT date FROM garmin_metrics"),
        "2026-10-30"
    );
    assert_eq!(query::<f64>(&db, "SELECT vo2max FROM garmin_metrics"), 52.4);
    // The primary training device's status, not the other device's, with
    // the API's numeric suffix dropped to match the export's vocabulary.
    assert_eq!(
        query::<String>(&db, "SELECT training_status FROM garmin_metrics"),
        "PRODUCTIVE"
    );
    assert_eq!(
        query::<f64>(&db, "SELECT acute_load FROM garmin_metrics"),
        480.0
    );
    assert_eq!(
        query::<f64>(&db, "SELECT chronic_load FROM garmin_metrics"),
        400.0
    );
    assert_eq!(
        query::<f64>(&db, "SELECT acute_chronic_ratio FROM garmin_metrics"),
        1.2
    );
    assert_eq!(
        query::<f64>(&db, "SELECT race_5k_s FROM garmin_metrics"),
        1260.0
    );
    assert_eq!(
        query::<f64>(&db, "SELECT race_10k_s FROM garmin_metrics"),
        2640.0
    );
    assert_eq!(
        query::<f64>(&db, "SELECT race_half_marathon_s FROM garmin_metrics"),
        5880.0
    );
    assert_eq!(
        query::<f64>(&db, "SELECT race_marathon_s FROM garmin_metrics"),
        12600.0
    );
    assert_eq!(source.requested_dates(GarminMetric::Vo2Max), vec![today()]);
    assert_eq!(
        query::<i64>(
            &db,
            "SELECT count(*) FROM sync_runs WHERE source = 'garminconnect' AND outcome = 'ok'"
        ),
        1
    );
}

/// An activity row as the activity sync leaves it; the metrics backfill
/// starts at the first activity.
fn add_activity(data_dir: &DataDir, id: i64, start_local: &str) {
    let conn = runsync::db::open(&data_dir.analysis_db_path()).unwrap();
    conn.execute(
        "INSERT INTO activities (activity_id, activity_type, start_time_utc, start_time_local)
         VALUES (?1, 'running', ?2, ?2)",
        rusqlite::params![id, start_local],
    )
    .unwrap();
}

#[test]
fn backfill_takes_one_sunday_per_week_back_to_the_first_activity_newest_first() {
    let (_dir, data_dir) = empty_data_dir();
    add_activity(&data_dir, 1, "2026-10-01T07:00:00"); // a Thursday
    add_activity(&data_dir, 2, "2026-10-20T07:00:00");
    let mut source = FakeMetrics::new();

    let report = sync_garmin_metrics(&data_dir, &mut source, &options()).unwrap();

    assert!(report.stopped_by.is_none());
    let expected: Vec<NaiveDate> = [
        "2026-10-30",
        "2026-10-25",
        "2026-10-18",
        "2026-10-11",
        "2026-10-04",
    ]
    .map(date)
    .to_vec();
    for metric in GarminMetric::ALL {
        assert_eq!(source.requested_dates(metric), expected, "{metric:?}");
    }
    assert_eq!(report.fetched, 15);
    let db = data_dir.analysis_db_path();
    assert_eq!(query::<i64>(&db, "SELECT count(*) FROM garmin_metrics"), 5);
    assert_eq!(
        query::<i64>(
            &db,
            "SELECT count(*) FROM garmin_metrics WHERE vo2max IS NOT NULL AND race_5k_s IS NOT NULL AND training_status IS NOT NULL"
        ),
        5
    );
}

#[test]
fn a_later_sync_only_refetches_todays_snapshot() {
    let (_dir, data_dir) = empty_data_dir();
    add_activity(&data_dir, 1, "2026-10-01T07:00:00");
    sync_garmin_metrics(&data_dir, &mut FakeMetrics::new(), &options()).unwrap();

    let mut source = FakeMetrics::new().with_offset(1.0);
    let report = sync_garmin_metrics(&data_dir, &mut source, &options()).unwrap();

    assert_eq!(source.requested_dates(GarminMetric::Vo2Max), vec![today()]);
    assert_eq!(report.fetched, 3);
    let db = data_dir.analysis_db_path();
    assert_eq!(
        query::<f64>(
            &db,
            "SELECT vo2max FROM garmin_metrics WHERE date = '2026-10-30'"
        ),
        53.4
    );
    assert!(
        std::fs::read_to_string(raw(&data_dir, "vo2max", "2026-10-30"))
            .unwrap()
            .contains("53.4")
    );
    assert_eq!(
        query::<f64>(
            &db,
            "SELECT vo2max FROM garmin_metrics WHERE date = '2026-10-25'"
        ),
        52.4
    );
}

#[test]
fn a_source_error_stops_the_run_at_once_and_records_its_kind() {
    for (failure, outcome) in [
        (Failure::RateLimited, "rate_limited"),
        (Failure::CredentialsRejected, "auth_failed"),
        (Failure::Other, "error"),
    ] {
        let (_dir, data_dir) = empty_data_dir();
        add_activity(&data_dir, 1, "2026-10-01T07:00:00");
        let mut source =
            FakeMetrics::new().failing(GarminMetric::Vo2Max, date("2026-10-18"), failure);

        let report = sync_garmin_metrics(&data_dir, &mut source, &options()).unwrap();

        let err = report.stopped_by.expect("stopped");
        assert_eq!(err.outcome(), outcome);
        // Nothing after the failing request was asked for.
        assert_eq!(
            source.requests.last(),
            Some(&(GarminMetric::Vo2Max, date("2026-10-18")))
        );
        assert!(raw(&data_dir, "training_status", "2026-10-18").is_file());
        assert!(!raw(&data_dir, "vo2max", "2026-10-18").exists());
        let db = data_dir.analysis_db_path();
        assert_eq!(
            query::<String>(
                &db,
                "SELECT outcome FROM sync_runs WHERE source = 'garminconnect'"
            ),
            outcome
        );
    }
}

#[test]
fn an_interrupted_backfill_resumes_where_it_stopped() {
    let (_dir, data_dir) = empty_data_dir();
    add_activity(&data_dir, 1, "2026-10-01T07:00:00");
    let mut failing = FakeMetrics::new().failing(
        GarminMetric::RacePredictor,
        date("2026-10-18"),
        Failure::RateLimited,
    );
    sync_garmin_metrics(&data_dir, &mut failing, &options()).unwrap();

    let mut source = FakeMetrics::new();
    let report = sync_garmin_metrics(&data_dir, &mut source, &options()).unwrap();

    assert!(report.stopped_by.is_none());
    let mut expected = vec![
        (GarminMetric::TrainingStatus, today()),
        (GarminMetric::Vo2Max, today()),
        (GarminMetric::RacePredictor, today()),
        (GarminMetric::RacePredictor, date("2026-10-18")),
    ];
    for day in ["2026-10-11", "2026-10-04"] {
        for metric in GarminMetric::ALL {
            expected.push((metric, date(day)));
        }
    }
    assert_eq!(source.requests, expected);
    let db = data_dir.analysis_db_path();
    assert_eq!(
        query::<i64>(
            &db,
            "SELECT count(*) FROM garmin_metrics WHERE race_5k_s IS NOT NULL"
        ),
        5
    );
}

#[test]
fn a_day_without_data_is_archived_and_stored_as_nulls() {
    let (_dir, data_dir) = empty_data_dir();
    let mut source = EmptyDays;

    let report = sync_garmin_metrics(&data_dir, &mut source, &options()).unwrap();

    assert!(report.stopped_by.is_none());
    assert_eq!(report.unparsable, 0);
    assert!(raw(&data_dir, "race_predictor", "2026-10-30").is_file());
    let db = data_dir.analysis_db_path();
    assert_eq!(
        query::<i64>(
            &db,
            "SELECT count(*) FROM garmin_metrics WHERE vo2max IS NULL AND race_5k_s IS NULL \
             AND training_status IS NULL AND acute_load IS NULL"
        ),
        1
    );
}

#[test]
fn a_response_that_is_not_json_is_kept_and_counted() {
    let (_dir, data_dir) = empty_data_dir();
    let mut source = NotJson;

    let report = sync_garmin_metrics(&data_dir, &mut source, &options()).unwrap();

    assert!(report.stopped_by.is_none());
    assert_eq!(report.unparsable, 3);
    assert!(raw(&data_dir, "vo2max", "2026-10-30").is_file());
}

/// Garmin answers days without data with empty lists or `{}`.
struct EmptyDays;

impl MetricsSource for EmptyDays {
    fn metric(&mut self, metric: GarminMetric, _: NaiveDate) -> Result<String, SourceError> {
        Ok(match metric {
            GarminMetric::TrainingStatus => r#"{"userId": 1, "mostRecentTrainingStatus": null}"#,
            GarminMetric::Vo2Max | GarminMetric::RacePredictor => "[]",
        }
        .to_string())
    }
}

struct NotJson;

impl MetricsSource for NotJson {
    fn metric(&mut self, _: GarminMetric, _: NaiveDate) -> Result<String, SourceError> {
        Ok("<html>".to_string())
    }
}

#[test]
fn rebuild_reloads_garmin_metrics_from_the_raw_archive() {
    let (_dir, data_dir) = empty_data_dir();
    add_activity(&data_dir, 1, "2026-10-20T07:00:00");
    sync_garmin_metrics(&data_dir, &mut FakeMetrics::new(), &options()).unwrap();
    std::fs::write(raw(&data_dir, "vo2max", "2026-10-25"), "not json").unwrap();

    let report = runsync::rebuild::rebuild(&data_dir).unwrap();

    assert_eq!(report.garmin_metrics, 5);
    assert_eq!(report.skipped, 1);
    let db = data_dir.analysis_db_path();
    assert_eq!(query::<i64>(&db, "SELECT count(*) FROM garmin_metrics"), 2);
    assert_eq!(
        query::<f64>(
            &db,
            "SELECT vo2max FROM garmin_metrics WHERE date = '2026-10-30'"
        ),
        52.4
    );
    assert_eq!(
        query::<String>(
            &db,
            "SELECT training_status FROM garmin_metrics WHERE date = '2026-10-25'"
        ),
        "PRODUCTIVE"
    );
}

#[test]
fn without_activities_only_the_snapshot_is_taken() {
    let (_dir, data_dir) = empty_data_dir();
    let mut source = FakeMetrics::new();

    sync_garmin_metrics(&data_dir, &mut source, &options()).unwrap();

    assert_eq!(source.requests.len(), 3);
}
