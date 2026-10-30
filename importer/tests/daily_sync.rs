//! Seam 2: daily summaries in `sync`, driven by an in-memory data source.
//! Assertions are on the raw archive, the analysis database and which date
//! ranges were asked of the source.

mod common;

use std::path::{Path, PathBuf};

use chrono::{DateTime, NaiveDate, TimeZone, Utc};
use rusqlite::{Connection, OptionalExtension};
use tempfile::TempDir;

use common::fake_source::{Failure, FakeSource};
use runsync::data_dir::DataDir;
use runsync::source::SourceError;
use runsync::sync::{SyncOptions, sync_activities};

fn now() -> DateTime<Utc> {
    Utc.with_ymd_and_hms(2026, 10, 30, 12, 0, 0).unwrap()
}

fn day(y: i32, m: u32, d: u32) -> NaiveDate {
    NaiveDate::from_ymd_opt(y, m, d).unwrap()
}

/// The sync's "today" (the runner's local date).
fn today() -> NaiveDate {
    day(2026, 10, 30)
}

fn options() -> SyncOptions {
    SyncOptions {
        now: now(),
        today: today(),
        page_size: 100,
    }
}

fn empty_data_dir() -> (TempDir, DataDir) {
    let dir = TempDir::new().unwrap();
    std::fs::write(dir.path().join("config.toml"), "").unwrap();
    let data_dir = DataDir::open(dir.path().to_path_buf()).unwrap();
    (dir, data_dir)
}

fn daily_file(data_dir: &DataDir, d: NaiveDate) -> PathBuf {
    data_dir
        .personal_api_daily_summaries_dir()
        .join(format!("{}.json", d.format("%Y-%m-%d")))
}

fn resting_hr(db: &Path, d: NaiveDate) -> Option<Option<i64>> {
    Connection::open(db)
        .unwrap()
        .query_row(
            "SELECT resting_hr_bpm FROM daily_wellness WHERE calendar_date = ?1",
            [d.format("%Y-%m-%d").to_string()],
            |r| r.get(0),
        )
        .optional()
        .unwrap()
}

#[test]
fn the_first_sync_fetches_the_last_7_days_first_and_stores_one_file_per_day() {
    let (_dir, data_dir) = empty_data_dir();
    let mut source = FakeSource::new(vec![])
        .with_daily(day(2026, 10, 24), Some(52))
        .with_daily(day(2026, 10, 30), Some(55));

    let report = sync_activities(&data_dir, &mut source, &options()).unwrap();

    assert!(report.stopped_by.is_none());
    assert_eq!(
        source.daily_requests.first(),
        Some(&(day(2026, 10, 24), day(2026, 10, 30)))
    );
    let file = std::fs::read_to_string(daily_file(&data_dir, day(2026, 10, 24))).unwrap();
    assert!(file.contains("\"calendarDate\":\"2026-10-24\""), "{file}");
    let db = data_dir.analysis_db_path();
    assert_eq!(resting_hr(&db, day(2026, 10, 24)), Some(Some(52)));
    assert_eq!(resting_hr(&db, day(2026, 10, 30)), Some(Some(55)));
}

#[test]
fn the_first_sync_backfills_back_to_2021_08_in_7_day_ranges_newest_first() {
    let (_dir, data_dir) = empty_data_dir();
    let mut source = FakeSource::new(vec![]);

    sync_activities(&data_dir, &mut source, &options()).unwrap();

    let requests = &source.daily_requests;
    assert_eq!(requests[1], (day(2026, 10, 17), day(2026, 10, 23)));
    assert_eq!(requests.last().unwrap().0, day(2021, 8, 1));
    for pair in requests.windows(2) {
        assert_eq!(
            pair[1].1.succ_opt().unwrap(),
            pair[0].0,
            "contiguous: {pair:?}"
        );
    }
    for (start, end) in requests {
        assert!(
            end.signed_duration_since(*start).num_days() < 7,
            "{start}..{end}"
        );
    }
    assert!(daily_file(&data_dir, day(2021, 8, 1)).is_file());
    assert!(!daily_file(&data_dir, day(2021, 7, 31)).exists());
}

#[test]
fn a_day_without_data_is_archived_as_null_and_gets_no_row() {
    let (_dir, data_dir) = empty_data_dir();
    let mut source = FakeSource::new(vec![]).with_daily(day(2026, 10, 1), None);

    sync_activities(&data_dir, &mut source, &options()).unwrap();

    let empty = std::fs::read_to_string(daily_file(&data_dir, day(2026, 10, 2))).unwrap();
    assert_eq!(empty, "null");
    let db = data_dir.analysis_db_path();
    assert_eq!(resting_hr(&db, day(2026, 10, 2)), None);
    // A row without a resting heart rate is still a row.
    assert_eq!(resting_hr(&db, day(2026, 10, 1)), Some(None));
}

#[test]
fn a_later_sync_refetches_and_upserts_the_last_7_days_only() {
    let (_dir, data_dir) = empty_data_dir();
    let mut first = FakeSource::new(vec![])
        .with_daily(day(2026, 10, 10), Some(50))
        .with_daily(day(2026, 10, 25), Some(60));
    sync_activities(&data_dir, &mut first, &options()).unwrap();

    // Garmin corrects both days afterwards.
    let mut second = FakeSource::new(vec![])
        .with_daily(day(2026, 10, 10), Some(49))
        .with_daily(day(2026, 10, 25), Some(58));
    let report = sync_activities(&data_dir, &mut second, &options()).unwrap();

    assert_eq!(
        second.daily_requests,
        vec![(day(2026, 10, 24), day(2026, 10, 30))]
    );
    assert_eq!(report.daily_summaries, 7);
    let db = data_dir.analysis_db_path();
    assert_eq!(resting_hr(&db, day(2026, 10, 25)), Some(Some(58)));
    assert_eq!(resting_hr(&db, day(2026, 10, 10)), Some(Some(50)));
    let rows: i64 = Connection::open(&db)
        .unwrap()
        .query_row("SELECT count(*) FROM daily_wellness", [], |r| r.get(0))
        .unwrap();
    assert_eq!(rows, 2);
}

#[test]
fn an_older_range_with_a_missing_day_file_is_fetched_again() {
    let (_dir, data_dir) = empty_data_dir();
    sync_activities(&data_dir, &mut FakeSource::new(vec![]), &options()).unwrap();
    std::fs::remove_file(daily_file(&data_dir, day(2026, 10, 12))).unwrap();

    let mut source = FakeSource::new(vec![]).with_daily(day(2026, 10, 12), Some(51));
    sync_activities(&data_dir, &mut source, &options()).unwrap();

    assert_eq!(
        source.daily_requests,
        vec![
            (day(2026, 10, 24), day(2026, 10, 30)),
            (day(2026, 10, 10), day(2026, 10, 16)),
        ]
    );
    assert_eq!(
        resting_hr(&data_dir.analysis_db_path(), day(2026, 10, 12)),
        Some(Some(51))
    );
}

#[test]
fn a_rate_limited_daily_request_stops_the_run_and_keeps_what_was_saved() {
    let (_dir, data_dir) = empty_data_dir();
    let mut source = FakeSource::new(vec![])
        .with_daily(day(2026, 10, 30), Some(55))
        .failing_daily(day(2026, 10, 20), Failure::RateLimited);

    let report = sync_activities(&data_dir, &mut source, &options()).unwrap();

    assert!(matches!(
        report.stopped_by,
        Some(SourceError::RateLimited(_))
    ));
    assert_eq!(source.daily_requests.len(), 2, "no request after the error");
    assert!(daily_file(&data_dir, day(2026, 10, 30)).is_file());
    assert!(!daily_file(&data_dir, day(2026, 10, 20)).exists());
    let outcome: String = Connection::open(data_dir.analysis_db_path())
        .unwrap()
        .query_row("SELECT outcome FROM sync_runs", [], |r| r.get(0))
        .unwrap();
    assert_eq!(outcome, "rate_limited");
}
