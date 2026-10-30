//! `runsync rebuild`: delete the analysis database and recreate it from the
//! raw archive. Fully offline.

use std::path::{Path, PathBuf};

use anyhow::{Context, Result};

use crate::activity::Activity;
use crate::data_dir::DataDir;
use crate::db;
use crate::fit::ActivityFit;

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct RebuildReport {
    /// Activity detail JSON files loaded into `activities`.
    pub activities: usize,
    /// FIT files loaded into `records` and `laps`.
    pub fit_files: usize,
    /// Files (JSON or FIT) that failed to load. They stay in the raw archive.
    pub skipped: usize,
}

pub fn rebuild(data_dir: &DataDir) -> Result<RebuildReport> {
    let db_path = data_dir.analysis_db_path();
    remove_database(&db_path)?;
    let mut conn = db::open(&db_path)?;

    let mut report = RebuildReport::default();
    let activities_dir = data_dir.personal_api_activities_dir();
    let tx = conn.transaction()?;
    for path in files_with_extension(&activities_dir, "json")? {
        let loaded = std::fs::read_to_string(&path)
            .map_err(anyhow::Error::from)
            .and_then(|text| Activity::from_detail_json(&text))
            .and_then(|a| a.upsert(&tx));
        match loaded {
            Ok(()) => report.activities += 1,
            Err(err) => {
                log::warn!("skipping {}: {err:#}", path.display());
                report.skipped += 1;
            }
        }
    }
    for path in files_with_extension(&activities_dir, "fit")? {
        match load_fit(&tx, &path) {
            Ok(()) => report.fit_files += 1,
            Err(err) => {
                log::warn!("skipping {}: {err:#}", path.display());
                report.skipped += 1;
            }
        }
    }
    tx.commit()?;
    Ok(report)
}

/// Parse `<activityId>.fit` and store it. On any error nothing from this
/// file is left in the database.
fn load_fit(conn: &rusqlite::Connection, path: &Path) -> Result<()> {
    let activity_id: i64 = path
        .file_stem()
        .and_then(|s| s.to_str())
        .and_then(|s| s.parse().ok())
        .context("file name is not <activityId>.fit")?;
    let bytes = std::fs::read(path)?;
    let fit = ActivityFit::parse(&bytes)?;
    conn.execute_batch("SAVEPOINT fit_file")?;
    match fit.store(conn, activity_id) {
        Ok(()) => {
            conn.execute_batch("RELEASE fit_file")?;
            Ok(())
        }
        Err(err) => {
            conn.execute_batch("ROLLBACK TO fit_file; RELEASE fit_file")?;
            Err(err)
        }
    }
}

/// Remove the database and its WAL side files.
fn remove_database(db_path: &Path) -> Result<()> {
    for suffix in ["", "-wal", "-shm"] {
        let mut p = db_path.as_os_str().to_owned();
        p.push(suffix);
        let p = PathBuf::from(p);
        if p.exists() {
            std::fs::remove_file(&p).with_context(|| {
                format!(
                    "deleting {} (is Jupyter or the dashboard holding it open?)",
                    p.display()
                )
            })?;
        }
    }
    Ok(())
}

fn files_with_extension(dir: &Path, extension: &str) -> Result<Vec<PathBuf>> {
    if !dir.is_dir() {
        return Ok(Vec::new());
    }
    let mut files: Vec<_> = std::fs::read_dir(dir)
        .with_context(|| format!("listing {}", dir.display()))?
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| {
            p.extension()
                .is_some_and(|ext| ext.eq_ignore_ascii_case(extension))
        })
        .collect();
    files.sort();
    Ok(files)
}
