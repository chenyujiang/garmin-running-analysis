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
    assert!(t.contains(&"hourly_weather".to_string()), "{t:?}");
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
    assert!(tables(&conn).contains(&"hourly_weather".to_string()));
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

/// FNV-1a 64 over the file with CRLF normalised to LF, so the hash is the
/// same on any checkout.
fn migration_hash(bytes: &[u8]) -> String {
    let text = String::from_utf8_lossy(bytes).replace("\r\n", "\n");
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for b in text.bytes() {
        h = (h ^ u64::from(b)).wrapping_mul(0x0100_0000_01b3);
    }
    format!("{h:016x}")
}

#[test]
fn shipped_migrations_are_never_edited() {
    let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("migrations");
    let manifest = std::fs::read_to_string(dir.join("checksums.txt")).unwrap();
    let expected: Vec<(String, String)> = manifest
        .lines()
        .filter(|l| !l.trim().is_empty() && !l.starts_with('#'))
        .map(|l| {
            let (name, hash) = l.split_once(' ').expect("line is `<file> <hash>`");
            (name.to_string(), hash.trim().to_string())
        })
        .collect();

    let mut files: Vec<String> = std::fs::read_dir(&dir)
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .filter(|n| n.ends_with(".sql"))
        .collect();
    files.sort();
    let actual: Vec<(String, String)> = files
        .into_iter()
        .map(|n| {
            let hash = migration_hash(&std::fs::read(dir.join(&n)).unwrap());
            (n, hash)
        })
        .collect();

    for ((name, want), (_, got)) in expected.iter().zip(&actual) {
        assert_eq!(
            want, got,
            "{name} was edited after it shipped; put the change in a new migration"
        );
    }
    assert_eq!(
        expected.len(),
        actual.len(),
        "migrations/checksums.txt and migrations/*.sql differ; for a new migration append \
         this line to checksums.txt: {:?}",
        actual.last()
    );
    let names = |v: &[(String, String)]| v.iter().map(|(n, _)| n.clone()).collect::<Vec<_>>();
    assert_eq!(names(&expected), names(&actual));
    assert_eq!(actual.len() as i64, runsync::db::LATEST_VERSION);
}
