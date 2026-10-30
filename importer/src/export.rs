//! `runsync import-export <zip>`: the Garmin account data export ("Export
//! Your Data") as a one-off history source.
//!
//! The package is copied verbatim to `raw/export/<export date>/<file name>`
//! and parsed from that copy, so `rebuild` can load it again. The export
//! date is the newest modification date of the package's entries.
//!
//! The package is untrusted input. Entries are only read into memory and
//! picked by name; nothing is ever written under an entry's name.

use std::collections::{BTreeSet, HashMap};
use std::io::{Cursor, Read, Seek};
use std::path::{Path, PathBuf};

use anyhow::{Context, Result, bail};
use chrono::{DateTime, NaiveDate};
use rusqlite::Connection;
use rusqlite::types::Value as SqlValue;
use serde::Deserialize;
use serde_json::Value;
use zip::ZipArchive;

use crate::activity::Activity;
use crate::daily::{self, sql_number};
use crate::data_dir::DataDir;
use crate::fit::ActivityFit;
use crate::source::GarminMetric;
use crate::{db, garmin_metrics};

/// Entries larger than this (uncompressed) are not read.
const MAX_ENTRY_BYTES: u64 = 1 << 30;

const FITNESS_DIR: &str = "DI_CONNECT/DI-Connect-Fitness/";
const ACTIVITIES_SUFFIX: &str = "_summarizedActivities.json";
/// Nested `UploadedFiles_*.zip` parts holding the uploaded FIT files.
const UPLOADED_DIR: &str = "DI_CONNECT/DI-Connect-Uploaded-Files/";
/// `UDSFile_*.json`: daily summaries.
const AGGREGATOR_DIR: &str = "DI_CONNECT/DI-Connect-Aggregator/";

/// What one package contributed to the analysis database.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct ExportReport {
    pub export_date: Option<NaiveDate>,
    /// The archived copy.
    pub archived: PathBuf,
    /// Activities loaded into `activities`.
    pub activities: usize,
    /// Activity FITs loaded into `records` and `laps`.
    pub fit_activities: usize,
    /// Activity FITs whose session start matches no activity of the package.
    pub fit_unmatched: usize,
    /// FIT files that are not activities (monitoring, settings, ...).
    pub fit_not_activity: usize,
    /// FIT files that could not be decoded.
    pub fit_failed: usize,
    /// Days loaded into `daily_wellness`.
    pub daily_days: BTreeSet<NaiveDate>,
    /// Days with a value loaded into `garmin_metrics`.
    pub metric_days: BTreeSet<NaiveDate>,
    /// Package values not loaded because the API archive already has them.
    pub kept_activities: usize,
    pub kept_fits: usize,
    pub kept_daily: usize,
    pub kept_metrics: usize,
}

impl std::fmt::Display for ExportReport {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        writeln!(f, "archived {}", self.archived.display())?;
        writeln!(f, "  activities: {}", self.activities)?;
        writeln!(
            f,
            "  FIT files: {} activities loaded, {} matching no activity, \
             {} not an activity (skipped), {} failed to parse",
            self.fit_activities, self.fit_unmatched, self.fit_not_activity, self.fit_failed
        )?;
        writeln!(f, "  daily summaries: {}", days(&self.daily_days))?;
        writeln!(f, "  Garmin metrics: {}", days(&self.metric_days))?;
        writeln!(
            f,
            "  kept from the API: {} activities, {} activity FITs, {} daily summaries, {} metric values",
            self.kept_activities, self.kept_fits, self.kept_daily, self.kept_metrics
        )
    }
}

/// "N days (first..last)".
fn days(set: &BTreeSet<NaiveDate>) -> String {
    match (set.first(), set.last()) {
        (Some(first), Some(last)) => format!("{} days ({first}..{last})", set.len()),
        _ => "0 days".to_owned(),
    }
}

/// Copy `zip` into the raw archive and load it. Returns one report per
/// package loaded, oldest first: the imported one and any newer ones,
/// reloaded so that they keep precedence.
pub fn import_export(data_dir: &DataDir, zip: &Path) -> Result<Vec<ExportReport>> {
    let file = std::fs::File::open(zip).with_context(|| format!("opening {}", zip.display()))?;
    let export_date = export_date(&mut ZipArchive::new(file).context("not a zip file")?)?;
    let name = zip.file_name().context("export path has no file name")?;
    let dir = data_dir
        .export_dir()
        .join(export_date.format("%Y-%m-%d").to_string());
    std::fs::create_dir_all(&dir).with_context(|| format!("creating {}", dir.display()))?;
    let archived = dir.join(name);
    copy_atomically(zip, &archived)?;

    // A newer package wins over an older one: load this one, then again
    // every archived package exported on or after it, oldest first.
    let mut conn = db::open(&data_dir.analysis_db_path())?;
    let tx = conn.transaction()?;
    let mut reports = Vec::new();
    for (date, path) in archived_packages(data_dir)? {
        if date >= export_date {
            reports.push(load_package(&tx, data_dir, &path)?);
        }
    }
    tx.commit()?;
    Ok(reports)
}

/// `raw/export/<YYYY-MM-DD>/*.zip`, oldest export first (then by path).
pub fn archived_packages(data_dir: &DataDir) -> Result<Vec<(NaiveDate, PathBuf)>> {
    let root = data_dir.export_dir();
    let mut packages = Vec::new();
    if !root.is_dir() {
        return Ok(packages);
    }
    for dir in std::fs::read_dir(&root).with_context(|| format!("listing {}", root.display()))? {
        let dir = dir?.path();
        let date = dir
            .file_name()
            .and_then(|n| n.to_str())
            .and_then(|n| NaiveDate::parse_from_str(n, "%Y-%m-%d").ok());
        let Some(date) = date.filter(|_| dir.is_dir()) else {
            continue;
        };
        for file in std::fs::read_dir(&dir).with_context(|| format!("listing {}", dir.display()))? {
            let file = file?.path();
            if file.is_file() && file.to_str().is_some_and(|n| has_extension(n, "zip")) {
                packages.push((date, file));
            }
        }
    }
    packages.sort();
    Ok(packages)
}

/// Load one archived package into the database.
/// Data already archived from the API (`raw/personal_api`, `raw/garminconnect`)
/// takes precedence: the package's value for it is not loaded.
pub fn load_package(conn: &Connection, data_dir: &DataDir, path: &Path) -> Result<ExportReport> {
    let file = std::fs::File::open(path).with_context(|| format!("opening {}", path.display()))?;
    let mut archive =
        ZipArchive::new(file).with_context(|| format!("reading {}", path.display()))?;
    let mut report = ExportReport {
        export_date: Some(export_date(&mut archive)?),
        archived: path.to_owned(),
        ..ExportReport::default()
    };
    let names = entry_names(&mut archive);
    let in_dir = |dir: &'static str, prefix: &'static str, extension: &'static str| {
        names.iter().filter(move |n| {
            n.strip_prefix(dir)
                .is_some_and(|f| !f.contains('/') && f.starts_with(prefix))
                && has_extension(n, extension)
        })
    };

    let mut loader = Loader {
        conn,
        report: &mut report,
        data_dir,
        by_start: HashMap::new(),
        daily_first: None,
    };
    for name in in_dir(FITNESS_DIR, "", "json").filter(|n| n.ends_with(ACTIVITIES_SUFFIX)) {
        let bytes = read_entry(&mut archive, name)?;
        loader
            .activities(&bytes)
            .with_context(|| format!("reading {name}"))?;
    }
    for name in in_dir(UPLOADED_DIR, "", "zip") {
        let bytes = read_entry(&mut archive, name)?;
        let part =
            ZipArchive::new(Cursor::new(bytes)).with_context(|| format!("reading {name}"))?;
        loader.fits(part)?;
    }
    for name in in_dir(AGGREGATOR_DIR, "UDSFile_", "json") {
        let bytes = read_entry(&mut archive, name)?;
        loader
            .daily(&bytes)
            .with_context(|| format!("reading {name}"))?;
    }
    let mut metrics = MetricDays::new();
    for (prefix, metric) in METRIC_FILES {
        for name in in_dir(METRICS_DIR, prefix, "json") {
            let bytes = read_entry(&mut archive, name)?;
            collect_metric(&mut metrics, metric, &bytes)
                .with_context(|| format!("reading {name}"))?;
        }
    }
    let metrics_first = metrics.keys().map(|(_, date)| *date).min();
    loader.metrics(metrics)?;
    let daily_first = loader.daily_first;
    record_coverage(conn, &report, daily_first, metrics_first)?;
    Ok(report)
}

/// Store what the package covers in `export_packages`, for sync to skip.
fn record_coverage(
    conn: &Connection,
    report: &ExportReport,
    daily_first: Option<NaiveDate>,
    metrics_first: Option<NaiveDate>,
) -> Result<()> {
    let export_date = report.export_date.context("package without export date")?;
    let package = format!(
        "{}/{}",
        export_date.format("%Y-%m-%d"),
        report
            .archived
            .file_name()
            .map(|n| n.to_string_lossy())
            .unwrap_or_default()
    );
    let date = |d: Option<NaiveDate>| d.map(|d| d.format("%Y-%m-%d").to_string());
    conn.execute(
        "INSERT INTO export_packages (package, export_date, daily_first, metrics_first)
         VALUES (?1, ?2, ?3, ?4)
         ON CONFLICT (package) DO UPDATE SET export_date = excluded.export_date,
             daily_first = excluded.daily_first, metrics_first = excluded.metrics_first",
        rusqlite::params![
            package,
            date(Some(export_date)),
            date(daily_first),
            date(metrics_first)
        ],
    )?;
    Ok(())
}

const METRICS_DIR: &str = "DI_CONNECT/DI-Connect-Metrics/";
/// Metrics file name prefixes. Each file is a list of rows with a
/// `calendarDate`; a day can have several rows, the latest one counts.
const METRIC_FILES: [(&str, GarminMetric); 3] = [
    ("MetricsMaxMetData_", GarminMetric::Vo2Max),
    ("RunRacePredictions_", GarminMetric::RacePredictor),
    ("TrainingHistory_", GarminMetric::TrainingStatus),
];

/// Per metric and day: the row's update time (as written, ISO-like, so it
/// sorts as text) and the `garmin_metrics` columns it sets.
type MetricDays = HashMap<(GarminMetric, NaiveDate), (String, Vec<(&'static str, SqlValue)>)>;

fn collect_metric(days: &mut MetricDays, metric: GarminMetric, bytes: &[u8]) -> Result<()> {
    let rows: Vec<Value> = serde_json::from_slice(bytes).context("not a metrics file")?;
    for row in rows {
        let Some(date) = calendar_date(&row) else {
            log::warn!("skipping a metrics row without calendarDate");
            continue;
        };
        let real = |key: &str| row[key].as_f64().map_or(SqlValue::Null, SqlValue::Real);
        let (updated, columns) = match metric {
            GarminMetric::Vo2Max => {
                // Cycling has its own VO2max; the API value is the running one.
                if row["sport"].as_str() != Some("RUNNING") {
                    continue;
                }
                (
                    &row["updateTimestamp"],
                    vec![("vo2max", real("vo2MaxValue"))],
                )
            }
            GarminMetric::RacePredictor => (
                &row["timestamp"],
                vec![
                    ("race_5k_s", real("raceTime5K")),
                    ("race_10k_s", real("raceTime10K")),
                    ("race_half_marathon_s", real("raceTimeHalf")),
                    ("race_marathon_s", real("raceTimeMarathon")),
                ],
            ),
            // Only the status: the export has no acute/chronic load.
            GarminMetric::TrainingStatus => (
                &row["timestamp"],
                vec![(
                    "training_status",
                    row["trainingStatus"]
                        .as_str()
                        .map_or(SqlValue::Null, |s| SqlValue::Text(s.to_owned())),
                )],
            ),
        };
        let updated = updated.as_str().unwrap_or_default().to_owned();
        match days.get(&(metric, date)) {
            Some((newest, _)) if *newest > updated => {}
            _ => {
                days.insert((metric, date), (updated, columns));
            }
        }
    }
    Ok(())
}

/// Loads the parts of one package, counting into `report`.
struct Loader<'a> {
    conn: &'a Connection,
    report: &'a mut ExportReport,
    data_dir: &'a DataDir,
    /// Activity FITs carry no activity id: they are matched to the package's
    /// activities by start time (Unix seconds).
    by_start: HashMap<i64, i64>,
    /// The first UDS day of the package, kept by the API or not.
    daily_first: Option<NaiveDate>,
}

impl Loader<'_> {
    /// `raw/personal_api/activities/<id>.<extension>`.
    fn api_file(&self, id: i64, extension: &str) -> PathBuf {
        self.data_dir
            .personal_api_activities_dir()
            .join(format!("{id}.{extension}"))
    }

    /// Whether the API archive has a daily summary row (not `null`) for
    /// `date`.
    fn api_has_day(&self, date: NaiveDate) -> bool {
        let path = self
            .data_dir
            .personal_api_daily_summaries_dir()
            .join(format!("{}.json", date.format("%Y-%m-%d")));
        std::fs::read_to_string(path).is_ok_and(|text| text.trim() != daily::NO_DATA)
    }

    fn activities(&mut self, bytes: &[u8]) -> Result<()> {
        for (begin, activity) in parse_activities(bytes)? {
            self.by_start.insert(begin, activity.activity_id);
            if self.api_file(activity.activity_id, "json").is_file() {
                self.report.kept_activities += 1;
                continue;
            }
            activity.upsert(self.conn)?;
            self.report.activities += 1;
        }
        Ok(())
    }

    fn fits(&mut self, mut part: ZipArchive<Cursor<Vec<u8>>>) -> Result<()> {
        for name in entry_names(&mut part)
            .into_iter()
            .filter(|n| has_extension(n, "fit"))
        {
            let loaded = read_entry(&mut part, &name).and_then(|bytes| self.fit(&bytes));
            match loaded {
                Ok(FitOutcome::Loaded) => self.report.fit_activities += 1,
                Ok(FitOutcome::Unmatched) => self.report.fit_unmatched += 1,
                Ok(FitOutcome::NotActivity) => self.report.fit_not_activity += 1,
                Ok(FitOutcome::KeptApi) => self.report.kept_fits += 1,
                Err(err) => {
                    log::debug!("skipping {name}: {err:#}");
                    self.report.fit_failed += 1;
                }
            }
        }
        Ok(())
    }

    fn fit(&mut self, bytes: &[u8]) -> Result<FitOutcome> {
        let fit = ActivityFit::parse(bytes)?;
        if !fit.is_activity() {
            return Ok(FitOutcome::NotActivity);
        }
        let id = fit
            .session_start
            .and_then(|t| self.by_start.get(&t.timestamp()).copied());
        let Some(id) = id else {
            return Ok(FitOutcome::Unmatched);
        };
        if self.api_file(id, "fit").is_file() {
            return Ok(FitOutcome::KeptApi);
        }
        fit.store_or_nothing(self.conn, id)?;
        Ok(FitOutcome::Loaded)
    }

    /// A `UDSFile_*.json`: a list of day rows.
    fn daily(&mut self, bytes: &[u8]) -> Result<()> {
        let rows: Vec<Value> = serde_json::from_slice(bytes).context("not a UDS file")?;
        for row in rows {
            let Some(date) = calendar_date(&row) else {
                log::warn!("skipping a UDS row without calendarDate");
                continue;
            };
            self.daily_first = Some(self.daily_first.map_or(date, |d| d.min(date)));
            if self.api_has_day(date) {
                self.report.kept_daily += 1;
                continue;
            }
            daily::store_values(self.conn, date, uds_values(&row))?;
            self.report.daily_days.insert(date);
        }
        Ok(())
    }

    fn metrics(&mut self, days: MetricDays) -> Result<()> {
        let mut days: Vec<_> = days.into_iter().collect();
        days.sort_by_key(|((metric, date), _)| (*date, metric.key()));
        let root = self.data_dir.garminconnect_dir();
        for ((metric, date), (_, columns)) in days {
            if garmin_metrics::metric_path(&root, metric, date).is_file() {
                self.report.kept_metrics += 1;
                continue;
            }
            garmin_metrics::upsert_columns(self.conn, date, columns)?;
            self.report.metric_days.insert(date);
        }
        Ok(())
    }
}

fn calendar_date(row: &Value) -> Option<NaiveDate> {
    NaiveDate::parse_from_str(row["calendarDate"].as_str()?, "%Y-%m-%d").ok()
}

/// A UDS row as the `daily_wellness` columns after `calendar_date`.
fn uds_values(row: &Value) -> [SqlValue; 14] {
    let n = |pointer: &str| sql_number(row.pointer(pointer));
    let find = |list: &Value, key: &str, wanted: &str| -> Option<Value> {
        list.as_array()?
            .iter()
            .find(|e| e[key].as_str() == Some(wanted))
            .cloned()
    };
    // Garmin writes negative stress levels for "no data".
    let stress = find(&row["allDayStress"]["aggregatorList"], "type", "TOTAL")
        .map(|a| a["averageStressLevel"].clone())
        .filter(|v| v.as_f64().is_some_and(|x| x >= 0.0));
    let battery = |kind: &str| {
        find(
            &row["bodyBattery"]["bodyBatteryStatList"],
            "bodyBatteryStatType",
            kind,
        )
        .map(|s| s["statsValue"].clone())
    };
    [
        n("/restingHeartRate"),
        n("/minHeartRate"),
        n("/maxHeartRate"),
        n("/totalSteps"),
        n("/totalDistanceMeters"),
        n("/totalKilocalories"),
        n("/activeKilocalories"),
        n("/bmrKilocalories"),
        n("/moderateIntensityMinutes"),
        n("/vigorousIntensityMinutes"),
        sql_number(stress.as_ref()),
        sql_number(battery("LOWEST").as_ref()),
        sql_number(battery("HIGHEST").as_ref()),
        n("/respiration/avgWakingRespirationValue"),
    ]
}

enum FitOutcome {
    Loaded,
    Unmatched,
    NotActivity,
    /// The activity's FIT is already archived from the API.
    KeptApi,
}

fn has_extension(name: &str, extension: &str) -> bool {
    Path::new(name)
        .extension()
        .is_some_and(|e| e.eq_ignore_ascii_case(extension))
}

/// The newest modification date of the package's entries.
fn export_date<R: Read + Seek>(archive: &mut ZipArchive<R>) -> Result<NaiveDate> {
    let mut newest = None;
    for i in 0..archive.len() {
        let entry = archive.by_index(i)?;
        if let Some(t) = entry.last_modified()
            && let Some(d) = NaiveDate::from_ymd_opt(
                i32::from(t.year()),
                u32::from(t.month()),
                u32::from(t.day()),
            )
        {
            newest = newest.max(Some(d));
        }
    }
    newest.context("the package's entries carry no modification date")
}

fn entry_names<R: Read + Seek>(archive: &mut ZipArchive<R>) -> Vec<String> {
    let mut names: Vec<String> = archive
        .file_names()
        .filter_map(|n| n.ok().map(|n| n.into_owned()))
        .collect();
    names.sort();
    names
}

fn read_entry<R: Read + Seek>(archive: &mut ZipArchive<R>, name: &str) -> Result<Vec<u8>> {
    let entry = archive.by_name(name)?;
    if entry.size() > MAX_ENTRY_BYTES {
        bail!("{name} is larger than {MAX_ENTRY_BYTES} bytes");
    }
    let mut bytes = Vec::with_capacity(entry.size() as usize);
    entry
        .take(MAX_ENTRY_BYTES + 1)
        .read_to_end(&mut bytes)
        .with_context(|| format!("reading {name}"))?;
    if bytes.len() as u64 > MAX_ENTRY_BYTES {
        bail!("{name} is larger than {MAX_ENTRY_BYTES} bytes");
    }
    Ok(bytes)
}

#[derive(Deserialize)]
struct ActivitiesFile {
    #[serde(rename = "summarizedActivitiesExport", default)]
    activities: Vec<Value>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct ExportActivity {
    activity_id: i64,
    activity_type: String,
    name: Option<String>,
    begin_timestamp: i64,
    start_time_local: f64,
    distance: Option<f64>,
    duration: Option<f64>,
    moving_duration: Option<f64>,
    elapsed_duration: Option<f64>,
    avg_speed: Option<f64>,
    max_speed: Option<f64>,
    avg_hr: Option<f64>,
    max_hr: Option<f64>,
    elevation_gain: Option<f64>,
    elevation_loss: Option<f64>,
    calories: Option<f64>,
}

/// Activity calories in the export are in units of kcal/4.19 (checked
/// against the FIT sessions' `total_calories`).
const EXPORT_CALORIES_PER_KCAL: f64 = 4.19;

/// The activities with their start as Unix seconds.
fn parse_activities(bytes: &[u8]) -> Result<Vec<(i64, Activity)>> {
    let files: Vec<ActivitiesFile> =
        serde_json::from_slice(bytes).context("not a summarizedActivities file")?;
    let mut activities = Vec::new();
    for value in files.into_iter().flat_map(|f| f.activities) {
        match serde_json::from_value::<ExportActivity>(value) {
            Ok(a) => activities.push((a.begin_timestamp.div_euclid(1000), a.into_activity()?)),
            Err(err) => log::warn!("skipping an export activity: {err}"),
        }
    }
    Ok(activities)
}

impl ExportActivity {
    fn into_activity(self) -> Result<Activity> {
        let utc = DateTime::from_timestamp_millis(self.begin_timestamp)
            .with_context(|| format!("activity {}: bad beginTimestamp", self.activity_id))?;
        // startTimeLocal is the local wall clock written as if it were UTC.
        let local = DateTime::from_timestamp_millis(self.start_time_local as i64)
            .with_context(|| format!("activity {}: bad startTimeLocal", self.activity_id))?;
        let div = |v: Option<f64>, by: f64| v.map(|v| v / by);
        Ok(Activity {
            activity_id: self.activity_id,
            activity_type: self.activity_type,
            activity_name: self.name,
            start_time_utc: utc.format("%Y-%m-%dT%H:%M:%SZ").to_string(),
            start_time_local: local.naive_utc().format("%Y-%m-%dT%H:%M:%S").to_string(),
            // The export only has Garmin's numeric time zone id.
            time_zone: None,
            distance_m: div(self.distance, 100.0),
            duration_s: div(self.duration, 1000.0),
            moving_duration_s: div(self.moving_duration, 1000.0),
            elapsed_duration_s: div(self.elapsed_duration, 1000.0),
            avg_speed_mps: self.avg_speed.map(|v| v * 10.0),
            max_speed_mps: self.max_speed.map(|v| v * 10.0),
            avg_hr_bpm: self.avg_hr,
            max_hr_bpm: self.max_hr,
            elevation_gain_m: div(self.elevation_gain, 100.0),
            elevation_loss_m: div(self.elevation_loss, 100.0),
            calories_kcal: div(self.calories, EXPORT_CALORIES_PER_KCAL),
        })
    }
}

/// Copy via a `.part` file and rename. Copying a file onto itself (importing
/// the archived copy again) does nothing.
fn copy_atomically(from: &Path, to: &Path) -> Result<()> {
    if let (Ok(a), Ok(b)) = (from.canonicalize(), to.canonicalize())
        && a == b
    {
        return Ok(());
    }
    let mut part = to.as_os_str().to_owned();
    part.push(".part");
    std::fs::copy(from, &part).with_context(|| format!("copying to {}", to.display()))?;
    std::fs::rename(&part, to).with_context(|| format!("writing {}", to.display()))?;
    Ok(())
}
