//! Seam 1: schema migrations bring any older analysis database to the latest version.

use rusqlite::Connection;
use tempfile::TempDir;

fn user_version(conn: &Connection) -> i64 {
    conn.query_row("PRAGMA user_version", [], |r| r.get(0))
        .unwrap()
}

fn tables(conn: &Connection) -> Vec<String> {
    let mut stmt = conn
        .prepare("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
        .unwrap();
    stmt.query_map([], |r| r.get(0))
        .unwrap()
        .map(Result::unwrap)
        .collect()
}

#[test]
fn an_empty_database_is_migrated_to_the_latest_version() {
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("running.sqlite");

    let conn = runsync::db::open(&path).unwrap();

    assert_eq!(user_version(&conn), runsync::db::LATEST_VERSION);
    let t = tables(&conn);
    assert!(t.contains(&"activities".to_string()), "{t:?}");
    assert!(t.contains(&"sync_runs".to_string()), "{t:?}");
}

#[test]
fn a_version_1_database_keeps_its_rows_and_reaches_the_latest_version() {
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("running.sqlite");
    {
        // A database as the first released importer left it: only migration 1.
        let conn = Connection::open(&path).unwrap();
        conn.execute_batch(include_str!("../migrations/0001_activities.sql"))
            .unwrap();
        conn.execute(
            "INSERT INTO activities (activity_id, activity_type, start_time_utc, start_time_local)
             VALUES (7, 'running', '2025-01-01T00:00:00Z', '2025-01-01T13:00:00')",
            [],
        )
        .unwrap();
        conn.pragma_update(None, "user_version", 1).unwrap();
    }

    let conn = runsync::db::open(&path).unwrap();

    assert_eq!(user_version(&conn), runsync::db::LATEST_VERSION);
    assert!(tables(&conn).contains(&"sync_runs".to_string()));
    let n: i64 = conn
        .query_row("SELECT count(*) FROM activities", [], |r| r.get(0))
        .unwrap();
    assert_eq!(n, 1);
}

#[test]
fn opening_twice_is_a_no_op() {
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("running.sqlite");
    drop(runsync::db::open(&path).unwrap());

    let conn = runsync::db::open(&path).unwrap();

    assert_eq!(user_version(&conn), runsync::db::LATEST_VERSION);
}

#[test]
fn a_database_from_a_newer_runsync_is_refused() {
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("running.sqlite");
    {
        let conn = Connection::open(&path).unwrap();
        conn.pragma_update(None, "user_version", runsync::db::LATEST_VERSION + 1)
            .unwrap();
    }

    let err = runsync::db::open(&path).unwrap_err();

    assert!(format!("{err:#}").contains("newer"), "{err:#}");
}
