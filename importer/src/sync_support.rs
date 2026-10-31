//! Helpers every data source's sync shares: writing raw archive files and
//! recording a run in `sync_runs`.

use std::path::Path;

use anyhow::{Context, Result};
use chrono::{SecondsFormat, Utc};
use rusqlite::{Connection, params};

/// Write via a `.part` file and rename, so a file in the archive is always
/// complete. An existing file is replaced.
pub(crate) fn write_atomically(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut part = path.as_os_str().to_owned();
    part.push(".part");
    std::fs::write(&part, bytes).with_context(|| format!("writing {}", path.display()))?;
    std::fs::rename(&part, path).with_context(|| format!("writing {}", path.display()))?;
    Ok(())
}

/// The current time as ISO 8601 UTC with a trailing Z, whole seconds.
pub(crate) fn utc_now_string() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Secs, true)
}

/// Record one sync run of `source` in `sync_runs`, finishing now.
pub(crate) fn record_sync_run(
    conn: &Connection,
    source: &str,
    started_at: &str,
    outcome: &str,
) -> Result<()> {
    conn.execute(
        "INSERT INTO sync_runs (source, started_at_utc, finished_at_utc, outcome)
         VALUES (?1, ?2, ?3, ?4)",
        params![source, started_at, utc_now_string(), outcome],
    )?;
    Ok(())
}
