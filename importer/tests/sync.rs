//! Seam 2: `sync` driven by an in-memory data source. Assertions are on the
//! raw archive, the analysis database and what was asked of the source.

mod common;

use std::path::{Path, PathBuf};

use chrono::{DateTime, Duration, TimeZone, Utc};
use rusqlite::Connection;
use tempfile::TempDir;

use common::fake_source::{Failure, FakeActivity, FakeSource};
use runsync::data_dir::DataDir;
use runsync::source::SourceError;
use runsync::sync::{SyncOptions, sync_activities};

fn now() -> DateTime<Utc> {
    Utc.with_ymd_and_hms(2026, 10, 30, 12, 0, 0).unwrap()
}

fn days_ago(days: i64) -> DateTime<Utc> {
    now() - Duration::days(days)
}

fn options(page_size: usize) -> SyncOptions {
    SyncOptions {
        now: now(),
        page_size,
    }
}

fn empty_data_dir() -> (TempDir, DataDir) {
    let dir = TempDir::new().unwrap();
    std::fs::write(dir.path().join("config.toml"), "").unwrap();
    let data_dir = DataDir::open(dir.path().to_path_buf()).unwrap();
    (dir, data_dir)
}

fn raw(data_dir: &DataDir, file: &str) -> PathBuf {
    data_dir.personal_api_activities_dir().join(file)
}

fn count(db: &Path, sql: &str) -> i64 {
    Connection::open(db)
        .unwrap()
        .query_row(sql, [], |r| r.get(0))
        .unwrap()
}

#[test]
fn backfill_stores_detail_and_fit_and_loads_them_into_the_database() {
    let (_dir, data_dir) = empty_data_dir();
    let mut source = FakeSource::new(vec![
        FakeActivity::run(101, days_ago(30), "Easy"),
        FakeActivity::run(102, days_ago(20), "Long"),
        FakeActivity::run(103, days_ago(10), "Tempo"),
    ]);

    let report = sync_activities(&data_dir, &mut source, &options(2)).unwrap();

    assert!(report.stopped_by.is_none());
    for id in [101, 102, 103] {
        assert!(raw(&data_dir, &format!("{id}.json")).is_file(), "{id}.json");
        assert!(raw(&data_dir, &format!("{id}.fit")).is_file(), "{id}.fit");
    }
    let db = data_dir.analysis_db_path();
    assert_eq!(count(&db, "SELECT count(*) FROM activities"), 3);
    assert_eq!(count(&db, "SELECT count(*) FROM records"), 6);
    assert_eq!(
        count(
            &db,
            "SELECT count(*) FROM sync_runs WHERE source = 'personal_api' AND outcome = 'ok'"
        ),
        1
    );
}

fn put(data_dir: &DataDir, file: &str, content: &str) {
    let path = raw(data_dir, file);
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    std::fs::write(path, content).unwrap();
}

fn read(data_dir: &DataDir, file: &str) -> String {
    std::fs::read_to_string(raw(data_dir, file)).unwrap()
}

#[test]
fn activities_already_in_the_archive_are_not_downloaded_again() {
    let (_dir, data_dir) = empty_data_dir();
    put(&data_dir, "101.json", "archived json");
    put(&data_dir, "101.fit", "archived fit");
    let mut source = FakeSource::new(vec![
        FakeActivity::run(101, days_ago(30), "Easy"),
        FakeActivity::run(102, days_ago(20), "Long"),
    ]);

    sync_activities(&data_dir, &mut source, &options(10)).unwrap();

    assert_eq!(read(&data_dir, "101.json"), "archived json");
    assert_eq!(read(&data_dir, "101.fit"), "archived fit");
    assert_eq!(source.detail_requests, vec![102]);
    assert_eq!(source.fit_requests, vec![102]);
}

#[test]
fn paging_stops_at_the_first_page_that_is_fully_archived() {
    let (_dir, data_dir) = empty_data_dir();
    for id in [101, 102, 103, 104] {
        put(&data_dir, &format!("{id}.json"), "archived");
        put(&data_dir, &format!("{id}.fit"), "archived");
    }
    // Newest first: 105 (new), 104 | 103, 102 | 101
    let mut source = FakeSource::new(vec![
        FakeActivity::run(101, days_ago(50), "a"),
        FakeActivity::run(102, days_ago(40), "b"),
        FakeActivity::run(103, days_ago(30), "c"),
        FakeActivity::run(104, days_ago(20), "d"),
        FakeActivity::run(105, days_ago(10), "e"),
    ]);

    let report = sync_activities(&data_dir, &mut source, &options(2)).unwrap();

    assert_eq!(source.list_requests, vec![(0, 2), (2, 2)]);
    assert_eq!(source.detail_requests, vec![105]);
    assert_eq!(report.new_activities, 1);
}

#[test]
fn paging_continues_past_an_archived_page_still_inside_the_last_7_days() {
    let (_dir, data_dir) = empty_data_dir();
    for id in [101, 102, 103] {
        put(&data_dir, &format!("{id}.json"), "archived");
        put(&data_dir, &format!("{id}.fit"), "archived");
    }
    let mut source = FakeSource::new(vec![
        FakeActivity::run(101, days_ago(20), "old"),
        FakeActivity::run(102, days_ago(5), "recent"),
        FakeActivity::run(103, days_ago(1), "recent"),
    ]);

    sync_activities(&data_dir, &mut source, &options(2)).unwrap();

    assert_eq!(source.list_requests, vec![(0, 2), (2, 2)]);
    assert_eq!(source.detail_requests, vec![103, 102]);
}

#[test]
fn details_from_the_last_7_days_are_overwritten_but_their_fit_is_kept() {
    let (_dir, data_dir) = empty_data_dir();
    put(&data_dir, "101.json", "old copy");
    put(&data_dir, "101.fit", "archived fit");
    put(&data_dir, "102.json", "old copy");
    let mut source = FakeSource::new(vec![
        FakeActivity::run(101, days_ago(6), "Renamed"),
        FakeActivity::run(102, days_ago(2), "Missing its FIT"),
    ]);

    let report = sync_activities(&data_dir, &mut source, &options(10)).unwrap();

    assert!(read(&data_dir, "101.json").contains("Renamed"));
    assert_eq!(read(&data_dir, "101.fit"), "archived fit");
    assert!(raw(&data_dir, "102.fit").is_file());
    assert_eq!(source.fit_requests, vec![102]);
    assert_eq!(report.refreshed_activities, 2);
    let name: String = Connection::open(data_dir.analysis_db_path())
        .unwrap()
        .query_row(
            "SELECT activity_name FROM activities WHERE activity_id = 101",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(name, "Renamed");
}

#[test]
fn details_older_than_7_days_are_not_refetched() {
    let (_dir, data_dir) = empty_data_dir();
    put(&data_dir, "101.json", "old copy");
    put(&data_dir, "101.fit", "archived fit");
    let mut source = FakeSource::new(vec![FakeActivity::run(101, days_ago(8), "Renamed")]);

    sync_activities(&data_dir, &mut source, &options(10)).unwrap();

    assert_eq!(read(&data_dir, "101.json"), "old copy");
    assert!(source.detail_requests.is_empty());
}

#[test]
fn an_activity_without_a_fit_file_is_stored_with_its_detail_only() {
    let (_dir, data_dir) = empty_data_dir();
    let mut source = FakeSource::new(vec![
        FakeActivity::run(101, days_ago(30), "Manual").without_fit(),
    ]);

    let report = sync_activities(&data_dir, &mut source, &options(10)).unwrap();

    assert!(report.stopped_by.is_none());
    assert!(raw(&data_dir, "101.json").is_file());
    assert!(!raw(&data_dir, "101.fit").exists());
}

#[test]
fn an_interrupted_backfill_resumes_where_it_stopped() {
    let (_dir, data_dir) = empty_data_dir();
    let activities = vec![
        FakeActivity::run(101, days_ago(30), "a"),
        FakeActivity::run(102, days_ago(20), "b"),
        FakeActivity::run(103, days_ago(10), "c"),
    ];
    let mut failing = FakeSource::new(activities.clone()).failing_detail(102, Failure::Other);

    let first = sync_activities(&data_dir, &mut failing, &options(10)).unwrap();

    assert!(matches!(first.stopped_by, Some(SourceError::Other(_))));
    assert!(raw(&data_dir, "103.json").is_file());
    assert!(!raw(&data_dir, "102.json").exists());
    assert!(!raw(&data_dir, "101.json").exists());
    let db = data_dir.analysis_db_path();
    assert_eq!(
        count(
            &db,
            "SELECT count(*) FROM sync_runs WHERE outcome = 'error'"
        ),
        1
    );

    let mut healthy = FakeSource::new(activities);
    let second = sync_activities(&data_dir, &mut healthy, &options(10)).unwrap();

    assert!(second.stopped_by.is_none());
    assert_eq!(healthy.detail_requests, vec![102, 101]);
    // 102's FIT was saved before the failure, so it is not fetched again.
    assert_eq!(healthy.fit_requests, vec![101]);
    assert_eq!(count(&db, "SELECT count(*) FROM activities"), 3);
}

#[test]
fn a_source_error_stops_the_run_and_records_its_kind() {
    for (failure, outcome) in [
        (Failure::RateLimited, "rate_limited"),
        (Failure::CredentialsRejected, "auth_failed"),
    ] {
        let (_dir, data_dir) = empty_data_dir();
        let mut source = FakeSource::new(vec![
            FakeActivity::run(101, days_ago(30), "a"),
            FakeActivity::run(102, days_ago(20), "b"),
        ])
        .failing_detail(102, failure);

        let report = sync_activities(&data_dir, &mut source, &options(10)).unwrap();

        assert!(report.stopped_by.is_some());
        assert_eq!(
            source.detail_requests,
            vec![102],
            "no request after the error"
        );
        let db = data_dir.analysis_db_path();
        assert_eq!(
            count(
                &db,
                &format!("SELECT count(*) FROM sync_runs WHERE outcome = '{outcome}'")
            ),
            1
        );
    }
}
