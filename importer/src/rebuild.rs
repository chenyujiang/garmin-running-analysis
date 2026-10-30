//! `runsync rebuild`: delete the analysis database and recreate it from the
//! raw archive. Fully offline.

use std::path::Path;

use anyhow::{Context, Result};

use crate::activity::Activity;
use crate::data_dir::DataDir;
use crate::db;

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct RebuildReport {
    pub activities: usize,
    pub skipped: usize,
}

pub fn rebuild(data_dir: &DataDir) -> Result<RebuildReport> {
    let db_path = data_dir.analysis_db_path();
    remove_database(&db_path)?;
    let mut conn = db::open(&db_path)?;

    let mut report = RebuildReport::default();
    let tx = conn.transaction()?;
    for path in json_files(&data_dir.personal_api_activities_dir())? {
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
    tx.commit()?;
    Ok(report)
}

/// Remove the database and its WAL side files.
fn remove_database(db_path: &Path) -> Result<()> {
    for suffix in ["", "-wal", "-shm"] {
        let mut p = db_path.as_os_str().to_owned();
        p.push(suffix);
        let p = std::path::PathBuf::from(p);
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

fn json_files(dir: &Path) -> Result<Vec<std::path::PathBuf>> {
    if !dir.is_dir() {
        return Ok(Vec::new());
    }
    let mut files: Vec<_> = std::fs::read_dir(dir)
        .with_context(|| format!("listing {}", dir.display()))?
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.extension().is_some_and(|ext| ext == "json"))
        .collect();
    files.sort();
    Ok(files)
}
