//! `runsync rebuild`: delete the analysis database and recreate it from the
//! raw archive. Fully offline.

use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use chrono::NaiveDate;

use crate::activity::Activity;
use crate::daily;
use crate::data_dir::DataDir;
use crate::fit::ActivityFit;
use crate::source::GarminMetric;
use crate::{db, export, garmin_metrics};

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct RebuildReport {
    /// Activity detail JSON files loaded into `activities`.
    pub activities: usize,
    /// FIT files loaded into `records` and `laps`.
    pub fit_files: usize,
    /// Daily summary files loaded into `daily_wellness` (`null` days excluded).
    pub daily_summaries: usize,
    /// garminconnect metric responses loaded into `garmin_metrics`.
    pub garmin_metrics: usize,
    /// Garmin account export packages (`raw/export/`) loaded.
    pub export_packages: usize,
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
    for path in files_with_extension(&data_dir.personal_api_daily_summaries_dir(), "json")? {
        let loaded = std::fs::read_to_string(&path)
            .map_err(anyhow::Error::from)
            .and_then(|text| daily::store_day(&tx, &text));
        match loaded {
            Ok(true) => report.daily_summaries += 1,
            Ok(false) => {}
            Err(err) => {
                log::warn!("skipping {}: {err:#}", path.display());
                report.skipped += 1;
            }
        }
    }
    load_garmin_metrics(&tx, &data_dir.garminconnect_dir(), &mut report)?;
    // Oldest first, so a newer package wins; the API data above is kept
    // (see `export::load_package`).
    for (_, path) in export::archived_packages(data_dir)? {
        tx.execute_batch("SAVEPOINT export_package")?;
        match export::load_package(&tx, data_dir, &path) {
            Ok(_) => {
                tx.execute_batch("RELEASE export_package")?;
                report.export_packages += 1;
            }
            Err(err) => {
                tx.execute_batch("ROLLBACK TO export_package; RELEASE export_package")?;
                log::warn!("skipping {}: {err:#}", path.display());
                report.skipped += 1;
            }
        }
    }
    tx.commit()?;
    Ok(report)
}

/// `raw/garminconnect/<metric>/<YYYY-MM-DD>.json` into `garmin_metrics`.
fn load_garmin_metrics(
    conn: &rusqlite::Connection,
    root: &Path,
    report: &mut RebuildReport,
) -> Result<()> {
    for metric in GarminMetric::ALL {
        for path in files_with_extension(&root.join(metric.key()), "json")? {
            let loaded = path
                .file_stem()
                .and_then(|s| s.to_str())
                .and_then(|s| NaiveDate::parse_from_str(s, "%Y-%m-%d").ok())
                .context("file name is not <YYYY-MM-DD>.json")
                .and_then(|date| {
                    let text = std::fs::read_to_string(&path)?;
                    garmin_metrics::store_metric(conn, metric, date, &text)
                });
            match loaded {
                Ok(()) => report.garmin_metrics += 1,
                Err(err) => {
                    log::warn!("skipping {}: {err:#}", path.display());
                    report.skipped += 1;
                }
            }
        }
    }
    Ok(())
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
    ActivityFit::parse(&bytes)?.store_or_nothing(conn, activity_id)
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
