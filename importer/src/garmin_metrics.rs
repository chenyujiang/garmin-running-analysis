//! `runsync sync` for Garmin's own metrics (Training Status, VO2max, Race
//! Predictor) from a [`MetricsSource`], kept only to compare with our own
//! numbers.
//!
//! - Every sync fetches today's snapshot of each metric and overwrites it.
//! - Backfill: one day per week (every Sunday before today, newest first)
//!   back to the week of the first activity in `activities`. A day/metric
//!   whose raw file exists is not fetched again, so an interrupted backfill
//!   resumes where it stopped. A day covered by an imported account export
//!   (`export_packages`) is not fetched either. The endpoints take a date, so history can be
//!   asked for (see ticket 06 for what the real API returned).
//! - Each response is stored as `raw/garminconnect/<metric>/<date>.json`
//!   and loaded into `garmin_metrics` (one row per day) at once.

use std::path::Path;

use anyhow::{Context, Result};
use chrono::{Datelike, Duration, NaiveDate, SecondsFormat, Utc};
use rusqlite::{Connection, params};
use serde_json::Value;

use crate::data_dir::DataDir;
use crate::db::{self, ExportCoverage};
use crate::source::{GarminMetric, MetricsSource, SourceError};

pub const SOURCE_NAME: &str = "garminconnect";

#[derive(Debug, Clone)]
pub struct MetricsSyncOptions {
    /// The snapshot day.
    pub today: NaiveDate,
}

#[derive(Debug, Default)]
pub struct MetricsSyncReport {
    /// Responses downloaded and archived.
    pub fetched: usize,
    /// Archived responses whose values could not be read.
    pub unparsable: usize,
    /// Set when the run stopped early; everything before it is kept.
    pub stopped_by: Option<SourceError>,
}

pub fn sync_garmin_metrics(
    data_dir: &DataDir,
    source: &mut dyn MetricsSource,
    options: &MetricsSyncOptions,
) -> Result<MetricsSyncReport> {
    let started_at = utc_now_string();
    let conn = db::open(&data_dir.analysis_db_path())?;
    let mut report = MetricsSyncReport::default();
    let root = data_dir.garminconnect_dir();

    let result = (|| -> Result<(), SourceError> {
        for metric in GarminMetric::ALL {
            fetch(&conn, &root, source, metric, options.today, &mut report)?;
        }
        for day in backfill_days(&conn, options.today)? {
            if db::export_covers(&conn, ExportCoverage::GarminMetrics, day)? {
                continue;
            }
            for metric in GarminMetric::ALL {
                if !metric_path(&root, metric, day).is_file() {
                    fetch(&conn, &root, source, metric, day, &mut report)?;
                }
            }
        }
        Ok(())
    })();
    if let Err(err) = result {
        log::warn!("garminconnect sync stopped: {err}");
        report.stopped_by = Some(err);
    }

    let outcome = report
        .stopped_by
        .as_ref()
        .map_or("ok", SourceError::outcome);
    conn.execute(
        "INSERT INTO sync_runs (source, started_at_utc, finished_at_utc, outcome)
         VALUES (?1, ?2, ?3, ?4)",
        params![SOURCE_NAME, started_at, utc_now_string(), outcome],
    )?;
    Ok(report)
}

/// The backfill days: every Sunday before `today`, newest first, back to the
/// week of the first activity. None without activities.
fn backfill_days(conn: &Connection, today: NaiveDate) -> Result<Vec<NaiveDate>, SourceError> {
    let first: Option<String> = conn
        .query_row(
            "SELECT min(substr(start_time_local, 1, 10)) FROM activities",
            [],
            |r| r.get(0),
        )
        .context("reading the first activity date")?;
    let Some(first) = first else {
        return Ok(Vec::new());
    };
    let first = NaiveDate::parse_from_str(&first, "%Y-%m-%d")
        .with_context(|| format!("first activity date {first:?}"))?;
    let mut day = today - Duration::days(i64::from(today.weekday().num_days_from_sunday()));
    if day == today {
        day -= Duration::days(7);
    }
    let mut days = Vec::new();
    while day >= first {
        days.push(day);
        day -= Duration::days(7);
    }
    Ok(days)
}

fn fetch(
    conn: &Connection,
    root: &Path,
    source: &mut dyn MetricsSource,
    metric: GarminMetric,
    date: NaiveDate,
    report: &mut MetricsSyncReport,
) -> Result<(), SourceError> {
    let json = source.metric(metric, date)?;
    let path = metric_path(root, metric, date);
    std::fs::create_dir_all(path.parent().expect("has a parent"))
        .with_context(|| format!("creating {}", path.display()))?;
    write_atomically(&path, json.as_bytes())?;
    report.fetched += 1;
    if let Err(err) = store_metric(conn, metric, date, &json) {
        log::warn!("could not load {}: {err:#}", path.display());
        report.unparsable += 1;
    }
    Ok(())
}

/// `raw/garminconnect/<metric>/<YYYY-MM-DD>.json` under `root`.
pub fn metric_path(root: &Path, metric: GarminMetric, date: NaiveDate) -> std::path::PathBuf {
    root.join(metric.key())
        .join(format!("{}.json", date.format("%Y-%m-%d")))
}

/// Upsert one metric's values for `date` into `garmin_metrics`, leaving the
/// other metrics' columns of that day alone. Fields missing from the
/// response are stored as NULL.
pub fn store_metric(
    conn: &Connection,
    metric: GarminMetric,
    date: NaiveDate,
    json: &str,
) -> Result<()> {
    let value: Value = serde_json::from_str(json).context("not JSON")?;
    let day = date.format("%Y-%m-%d").to_string();
    let columns: Vec<(&str, rusqlite::types::Value)> = match metric {
        GarminMetric::TrainingStatus => {
            let status = primary_training_status(&value);
            let load = status.map(|s| &s["acuteTrainingLoadDTO"]);
            vec![
                (
                    "training_status",
                    text(
                        status
                            .and_then(|s| s["trainingStatusFeedbackPhrase"].as_str())
                            .map(training_status_name),
                    ),
                ),
                (
                    "acute_load",
                    real(load.map(|l| &l["dailyTrainingLoadAcute"])),
                ),
                (
                    "chronic_load",
                    real(load.map(|l| &l["dailyTrainingLoadChronic"])),
                ),
                (
                    "acute_chronic_ratio",
                    real(load.map(|l| &l["dailyAcuteChronicWorkloadRatio"])),
                ),
            ]
        }
        GarminMetric::Vo2Max => {
            let entry = entry_for_day(&value, &day, |e| &e["generic"]["calendarDate"]);
            vec![(
                "vo2max",
                real(entry.map(|e| &e["generic"]["vo2MaxPreciseValue"])),
            )]
        }
        GarminMetric::RacePredictor => {
            let entry = entry_for_day(&value, &day, |e| &e["calendarDate"]);
            vec![
                ("race_5k_s", real(entry.map(|e| &e["time5K"]))),
                ("race_10k_s", real(entry.map(|e| &e["time10K"]))),
                (
                    "race_half_marathon_s",
                    real(entry.map(|e| &e["timeHalfMarathon"])),
                ),
                ("race_marathon_s", real(entry.map(|e| &e["timeMarathon"]))),
            ]
        }
    };

    upsert_columns(conn, date, columns)
}

/// Upsert `columns` of `date`'s `garmin_metrics` row, leaving the other
/// columns alone.
pub fn upsert_columns(
    conn: &Connection,
    date: NaiveDate,
    columns: Vec<(&str, rusqlite::types::Value)>,
) -> Result<()> {
    let day = date.format("%Y-%m-%d").to_string();
    let names: Vec<&str> = columns.iter().map(|(n, _)| *n).collect();
    let placeholders: Vec<String> = (2..=columns.len() + 1).map(|i| format!("?{i}")).collect();
    let updates: Vec<String> = names
        .iter()
        .map(|n| format!("{n} = excluded.{n}"))
        .collect();
    let sql = format!(
        "INSERT INTO garmin_metrics (date, {}) VALUES (?1, {})
         ON CONFLICT (date) DO UPDATE SET {}",
        names.join(", "),
        placeholders.join(", "),
        updates.join(", ")
    );
    let mut values: Vec<rusqlite::types::Value> = vec![day.into()];
    values.extend(columns.into_iter().map(|(_, v)| v));
    conn.execute(&sql, rusqlite::params_from_iter(values))?;
    Ok(())
}

/// `mostRecentTrainingStatus.latestTrainingStatusData` holds one entry per
/// device; use the one marked as primary training device, else the first.
fn primary_training_status(value: &Value) -> Option<&Value> {
    let devices = value["mostRecentTrainingStatus"]["latestTrainingStatusData"].as_object()?;
    devices
        .values()
        .find(|d| d["primaryTrainingDevice"].as_bool() == Some(true))
        .or_else(|| devices.values().next())
}

/// The API's feedback phrase carries a numeric variant (`PRODUCTIVE_1`);
/// the account export has only the status (`PRODUCTIVE`). Drop the suffix
/// so both sources store the same name.
fn training_status_name(phrase: &str) -> &str {
    match phrase.rsplit_once('_') {
        Some((name, n)) if !n.is_empty() && n.bytes().all(|b| b.is_ascii_digit()) => name,
        _ => phrase,
    }
}

/// The responses are lists with one entry per day (or a single object);
/// take the entry for `day`, else the last one.
fn entry_for_day<'a>(
    value: &'a Value,
    day: &str,
    calendar_date: impl Fn(&Value) -> &Value,
) -> Option<&'a Value> {
    match value {
        Value::Array(entries) => entries
            .iter()
            .find(|e| calendar_date(e).as_str() == Some(day))
            .or_else(|| entries.last()),
        Value::Object(_) => Some(value),
        _ => None,
    }
}

fn real(v: Option<&Value>) -> rusqlite::types::Value {
    v.and_then(Value::as_f64)
        .map_or(rusqlite::types::Value::Null, rusqlite::types::Value::Real)
}

fn text(v: Option<&str>) -> rusqlite::types::Value {
    v.map_or(rusqlite::types::Value::Null, |s| {
        rusqlite::types::Value::Text(s.to_owned())
    })
}

/// Write via a `.part` file and rename, so a file in the archive is always
/// complete. An existing file is replaced.
fn write_atomically(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut part = path.as_os_str().to_owned();
    part.push(".part");
    std::fs::write(&part, bytes).with_context(|| format!("writing {}", path.display()))?;
    std::fs::rename(&part, path).with_context(|| format!("writing {}", path.display()))?;
    Ok(())
}

fn utc_now_string() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Secs, true)
}
