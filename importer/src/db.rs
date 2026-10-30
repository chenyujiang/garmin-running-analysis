//! The SQLite analysis database. The schema is owned here: hand-written SQL
//! files in `migrations/`, compiled in with `include_str!`, versioned with
//! `PRAGMA user_version` and applied in one transaction on open.

use std::path::Path;

use anyhow::{Context, Result, bail};
use rusqlite::Connection;

/// Migration N (1-based) is `MIGRATIONS[N - 1]`. Append only; never edit a
/// migration that has shipped.
const MIGRATIONS: &[&str] = &[
    include_str!("../migrations/0001_activities.sql"),
    include_str!("../migrations/0002_sync_runs.sql"),
    include_str!("../migrations/0003_records_laps.sql"),
    include_str!("../migrations/0004_daily_wellness.sql"),
    include_str!("../migrations/0005_garmin_metrics.sql"),
];

pub const LATEST_VERSION: i64 = MIGRATIONS.len() as i64;

/// Open (or create) the analysis database, switch it to WAL and bring the
/// schema up to `LATEST_VERSION`.
pub fn open(path: &Path) -> Result<Connection> {
    let mut conn = Connection::open(path).with_context(|| format!("opening {}", path.display()))?;
    conn.pragma_update(None, "journal_mode", "WAL")?;
    conn.pragma_update(None, "foreign_keys", "ON")?;
    migrate(&mut conn).with_context(|| format!("migrating {}", path.display()))?;
    Ok(conn)
}

fn migrate(conn: &mut Connection) -> Result<()> {
    let tx = conn.transaction()?;
    let current: i64 = tx.query_row("PRAGMA user_version", [], |r| r.get(0))?;
    if current > LATEST_VERSION {
        bail!(
            "database schema version {current} is newer than this runsync \
             ({LATEST_VERSION}); update runsync or run `runsync rebuild`"
        );
    }
    for (i, sql) in MIGRATIONS.iter().enumerate().skip(current as usize) {
        let version = i as i64 + 1;
        tx.execute_batch(sql)
            .with_context(|| format!("applying migration {version}"))?;
        tx.pragma_update(None, "user_version", version)?;
        log::info!("applied migration {version}");
    }
    tx.commit()?;
    Ok(())
}
