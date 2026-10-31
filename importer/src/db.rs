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
    include_str!("../migrations/0006_export_packages.sql"),
    include_str!("../migrations/0007_hourly_weather.sql"),
];

/// Whether an imported export package covers `date` for `kind`: the day
/// lies between the package's first row of that kind and its export date.
pub fn export_covers(
    conn: &Connection,
    kind: ExportCoverage,
    date: chrono::NaiveDate,
) -> Result<bool> {
    let sql = format!(
        "SELECT EXISTS (SELECT 1 FROM export_packages
                        WHERE {0} IS NOT NULL AND {0} <= ?1 AND ?1 <= export_date)",
        kind.column()
    );
    let day = date.format("%Y-%m-%d").to_string();
    Ok(conn.query_row(&sql, [day], |r| r.get(0))?)
}

/// What an export package covers (see `migrations/0006_export_packages.sql`).
#[derive(Debug, Clone, Copy)]
pub enum ExportCoverage {
    DailySummaries,
    GarminMetrics,
}

impl ExportCoverage {
    fn column(self) -> &'static str {
        match self {
            ExportCoverage::DailySummaries => "daily_first",
            ExportCoverage::GarminMetrics => "metrics_first",
        }
    }
}

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
