//! A hand-written, synthetic Garmin account export package for the
//! `import-export` tests. It has the real package's layout and field names
//! but made-up values: no GPS positions, no e-mail address (the real file
//! names start with the account's e-mail; here they start with `synthetic`).
//!
//! Units follow the real export: distances and elevations in cm, durations
//! in ms, speeds in 10 m/s (sic), activity calories in units of kcal/4.19.

#![allow(dead_code)]

use std::io::{Cursor, Write};
use std::path::Path;

use chrono::{DateTime, Duration, NaiveDate, TimeZone, Utc};
use serde_json::{Value, json};
use zip::write::SimpleFileOptions;

use super::fit::{
    ENUM, FitWriter, MESG_FILE_ID, MESG_LAP, MESG_RECORD, UINT8, UINT32, field, fit_time,
};

pub const MESG_SESSION: u16 = 18;
/// FIT `file` enum values.
pub const FILE_ACTIVITY: i64 = 4;
pub const FILE_MONITORING_B: i64 = 32;

const FITNESS: &str = "DI_CONNECT/DI-Connect-Fitness";
const UPLOADED: &str = "DI_CONNECT/DI-Connect-Uploaded-Files";
const AGGREGATOR: &str = "DI_CONNECT/DI-Connect-Aggregator";
const METRICS: &str = "DI_CONNECT/DI-Connect-Metrics";

/// Builds an export zip entry by entry. Every entry carries the same
/// modification date: the export date.
pub struct ExportZip {
    exported: NaiveDate,
    entries: Vec<(String, Vec<u8>)>,
}

impl ExportZip {
    pub fn new(exported: NaiveDate) -> Self {
        Self {
            exported,
            entries: Vec::new(),
        }
    }

    pub fn entry(mut self, name: &str, bytes: impl Into<Vec<u8>>) -> Self {
        self.entries.push((name.to_owned(), bytes.into()));
        self
    }

    /// `summarizedActivities.json` part `n` holding `activities`.
    pub fn activities(self, n: usize, activities: Vec<Value>) -> Self {
        let body = json!([{ "summarizedActivitiesExport": activities }]).to_string();
        self.entry(
            &format!("{FITNESS}/synthetic_{n}_summarizedActivities.json"),
            body,
        )
    }

    /// A nested `UploadedFiles_0-_Part<n>.zip` holding `fits` by file name.
    pub fn uploaded_fits(self, n: usize, fits: Vec<(&str, Vec<u8>)>) -> Self {
        let inner = zip_bytes(
            self.exported,
            fits.into_iter()
                .map(|(name, b)| (name.to_owned(), b))
                .collect(),
        );
        self.entry(&format!("{UPLOADED}/UploadedFiles_0-_Part{n}.zip"), inner)
    }

    pub fn uds(self, name: &str, rows: Vec<Value>) -> Self {
        self.entry(
            &format!("{AGGREGATOR}/UDSFile_{name}.json"),
            Value::Array(rows).to_string(),
        )
    }

    pub fn metrics(self, prefix: &str, name: &str, rows: Vec<Value>) -> Self {
        self.entry(
            &format!("{METRICS}/{prefix}_{name}.json"),
            Value::Array(rows).to_string(),
        )
    }

    pub fn bytes(&self) -> Vec<u8> {
        zip_bytes(self.exported, self.entries.clone())
    }

    pub fn write(&self, path: &Path) {
        std::fs::write(path, self.bytes()).unwrap();
    }
}

fn zip_bytes(modified: NaiveDate, entries: Vec<(String, Vec<u8>)>) -> Vec<u8> {
    use chrono::Datelike;
    let time = zip::DateTime::from_date_and_time(
        modified.year() as u16,
        modified.month() as u8,
        modified.day() as u8,
        9,
        30,
        0,
    )
    .unwrap();
    let options = SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Stored)
        .last_modified_time(time);
    let mut writer = zip::ZipWriter::new(Cursor::new(Vec::new()));
    for (name, bytes) in entries {
        writer.start_file(name, options).unwrap();
        writer.write_all(&bytes).unwrap();
    }
    writer.finish().unwrap().into_inner()
}

pub fn utc(y: i32, m: u32, d: u32, h: u32, min: u32) -> DateTime<Utc> {
    Utc.with_ymd_and_hms(y, m, d, h, min, 0).unwrap()
}

/// One `summarizedActivitiesExport` entry in the export's units. The local
/// start is 13 h ahead of UTC (NZDT). `km`, `s` and `kcal` are SI/kcal and
/// are converted to the export's units here.
pub fn activity(id: i64, activity_type: &str, start: DateTime<Utc>, km: f64, s: f64) -> Value {
    activity_with_offset(id, activity_type, start, km, s, Duration::hours(13))
}

/// [`activity`] with the local start `offset` ahead of UTC.
pub fn activity_with_offset(
    id: i64,
    activity_type: &str,
    start: DateTime<Utc>,
    km: f64,
    s: f64,
    offset: Duration,
) -> Value {
    let begin = start.timestamp_millis();
    let local = (start + offset).timestamp_millis();
    json!({
        "activityId": id,
        "uuidMsb": 1, "uuidLsb": 2,
        "name": format!("Synthetic {activity_type} {id}"),
        "activityType": activity_type,
        "userProfileId": 1,
        "timeZoneId": 130,
        "beginTimestamp": begin,
        "eventTypeId": 9,
        "sportType": "RUNNING",
        "startTimeGmt": begin as f64,
        "startTimeLocal": local as f64,
        "duration": s * 1000.0,
        "elapsedDuration": (s + 60.0) * 1000.0,
        "movingDuration": (s - 30.0) * 1000.0,
        "distance": km * 100_000.0,
        "elevationGain": 4250.0,
        "elevationLoss": 4100.0,
        "avgSpeed": km * 1000.0 / s / 10.0,
        "maxSpeed": 0.45,
        "avgHr": 151.0,
        "maxHr": 176.0,
        "calories": 600.0 * 4.19,
        "bmrCalories": 80.0,
        "lapCount": 1,
        "parent": false
    })
}

/// A tiny activity FIT: `file_id` (type activity), two records, one lap,
/// one session starting at `start`.
pub fn activity_fit(start: DateTime<Utc>) -> Vec<u8> {
    let t = start.timestamp();
    FitWriter::new()
        .message(
            MESG_FILE_ID,
            &[field(0, ENUM, FILE_ACTIVITY), field(4, UINT32, fit_time(t))],
        )
        .message(
            MESG_RECORD,
            &[field(253, UINT32, fit_time(t)), field(3, UINT8, 140)],
        )
        .message(
            MESG_RECORD,
            &[field(253, UINT32, fit_time(t + 1)), field(3, UINT8, 142)],
        )
        .message(
            MESG_LAP,
            &[
                field(253, UINT32, fit_time(t + 1)),
                field(2, UINT32, fit_time(t)),
                field(9, UINT32, 250), // total_distance, 2.5 m
            ],
        )
        .message(
            MESG_SESSION,
            &[
                field(253, UINT32, fit_time(t + 1)),
                field(2, UINT32, fit_time(t)),
                field(5, ENUM, 1), // sport: running
            ],
        )
        .finish()
}

/// A daily monitoring FIT (not an activity) with one record-shaped message.
pub fn monitoring_fit(start: DateTime<Utc>) -> Vec<u8> {
    let t = start.timestamp();
    FitWriter::new()
        .message(
            MESG_FILE_ID,
            &[
                field(0, ENUM, FILE_MONITORING_B),
                field(4, UINT32, fit_time(t)),
            ],
        )
        .message(
            MESG_RECORD,
            &[field(253, UINT32, fit_time(t)), field(3, UINT8, 60)],
        )
        .finish()
}

/// A UDS daily row. `stress` is the TOTAL aggregator's average (Garmin
/// writes negative values for "no data").
pub fn uds_row(day: NaiveDate, resting_hr: Option<i64>, stress: i64) -> Value {
    let date = day.format("%Y-%m-%d").to_string();
    let mut row = json!({
        "userProfilePK": 1,
        "calendarDate": date,
        "durationInMilliseconds": 86_400_000,
        "totalKilocalories": 2210.0,
        "activeKilocalories": 560.0,
        "bmrKilocalories": 1650.0,
        "totalSteps": 9100,
        "totalDistanceMeters": 7320,
        "moderateIntensityMinutes": 14,
        "vigorousIntensityMinutes": 33,
        "minHeartRate": 47,
        "maxHeartRate": 172,
        "allDayStress": {
            "calendarDate": date,
            "aggregatorList": [
                { "type": "TOTAL", "averageStressLevel": stress, "maxStressLevel": 90 },
                { "type": "AWAKE", "averageStressLevel": 99, "maxStressLevel": 99 }
            ]
        },
        "bodyBattery": {
            "bodyBatteryStatList": [
                { "bodyBatteryStatType": "LOWEST", "statsValue": 22 },
                { "bodyBatteryStatType": "HIGHEST", "statsValue": 87 },
                { "bodyBatteryStatType": "ENDOFDAY", "statsValue": 40 }
            ]
        },
        "respiration": { "avgWakingRespirationValue": 15.0, "highestRespirationValue": 22.0 }
    });
    if let Some(hr) = resting_hr {
        row["restingHeartRate"] = json!(hr);
    }
    row
}

pub fn vo2max_row(day: NaiveDate, sport: &str, updated: &str, value: f64) -> Value {
    json!({
        "userProfilePK": 1,
        "calendarDate": day.format("%Y-%m-%d").to_string(),
        "deviceId": 1,
        "updateTimestamp": updated,
        "sport": sport,
        "subSport": "GENERIC",
        "vo2MaxValue": value,
        "maxMet": value / 3.5,
        "calibratedData": 1
    })
}

pub fn race_row(day: NaiveDate, timestamp: &str, time_5k: i64) -> Value {
    json!({
        "userProfilePK": 1,
        "calendarDate": day.format("%Y-%m-%d").to_string(),
        "deviceId": 1,
        "timestamp": timestamp,
        "raceTime5K": time_5k,
        "raceTime10K": 2500,
        "raceTimeHalf": 5900,
        "raceTimeMarathon": 13400
    })
}

pub fn training_row(day: NaiveDate, timestamp: &str, status: &str) -> Value {
    json!({
        "userProfilePK": 1,
        "calendarDate": day.format("%Y-%m-%d").to_string(),
        "deviceId": 1,
        "timestamp": timestamp,
        "sport": "RUNNING",
        "subSport": "GENERIC",
        "weeklyTrainingLoadSum": 372,
        "loadTunnelMin": 281,
        "loadTunnelMax": 640,
        "trainingStatus": status,
        "fitnessLevelTrend": "NO_CHANGE",
        "loadLevelTrend": "NO_CHANGE"
    })
}

pub fn day(y: i32, m: u32, d: u32) -> NaiveDate {
    NaiveDate::from_ymd_opt(y, m, d).unwrap()
}

/// The standard fixture package, exported 2026-10-28:
///
/// - activities 9001 (running, 10 km in 3000 s, 2026-10-20 06:00Z, has a
///   FIT), 9002 (strength_training, 2026-10-22, no FIT) and 9003 (running,
///   2026-09-27 05:00Z, has a FIT);
/// - uploaded FITs: the two activity FITs, a monitoring FIT, a FIT that
///   matches no activity and a file that is not FIT at all;
/// - UDS rows for every day 2026-10-01..=2026-10-28;
/// - metrics for 2026-10-01 and 2026-10-20 (two VO2max updates and a cycling
///   value that day, two race predictions, a training status).
pub fn standard_package() -> ExportZip {
    let uds: Vec<Value> = day(2026, 10, 1)
        .iter_days()
        .take_while(|d| *d <= day(2026, 10, 28))
        .map(|d| {
            if d == day(2026, 10, 21) {
                uds_row(d, None, -1)
            } else {
                uds_row(d, Some(46), 25)
            }
        })
        .collect();
    let d20 = day(2026, 10, 20);
    let d01 = day(2026, 10, 1);
    ExportZip::new(day(2026, 10, 28))
        .activities(
            1,
            vec![
                activity(9001, "running", utc(2026, 10, 20, 6, 0), 10.0, 3000.0),
                activity(
                    9002,
                    "strength_training",
                    utc(2026, 10, 22, 7, 0),
                    0.0,
                    1800.0,
                ),
            ],
        )
        .activities(
            301,
            vec![activity(
                9003,
                "running",
                utc(2026, 9, 27, 5, 0),
                5.0,
                1500.0,
            )],
        )
        .uploaded_fits(
            1,
            vec![
                (
                    "synthetic_100000000001.fit",
                    activity_fit(utc(2026, 10, 20, 6, 0)),
                ),
                (
                    "synthetic_100000000002.fit",
                    monitoring_fit(utc(2026, 10, 20, 0, 0)),
                ),
                ("synthetic_100000000003.fit", b"not a FIT file".to_vec()),
            ],
        )
        .uploaded_fits(
            2,
            vec![
                (
                    "synthetic_100000000004.fit",
                    activity_fit(utc(2026, 9, 27, 5, 0)),
                ),
                (
                    "synthetic_100000000005.fit",
                    activity_fit(utc(2026, 10, 25, 8, 0)),
                ),
            ],
        )
        .uds("2026-10-01_2026-10-28", uds)
        .metrics(
            "MetricsMaxMetData",
            "20261001_20261028_1",
            vec![
                vo2max_row(d01, "RUNNING", "2026-10-01T08:00:00.0", 54.0),
                vo2max_row(d20, "RUNNING", "2026-10-20T08:00:00.0", 55.0),
                vo2max_row(d20, "RUNNING", "2026-10-20T09:00:00.0", 56.0),
                vo2max_row(d20, "CYCLING", "2026-10-20T10:00:00.0", 60.0),
            ],
        )
        .metrics(
            "RunRacePredictions",
            "20261001_20261028_1",
            vec![
                race_row(d20, "2026-10-20T12:00:00.0", 1150),
                race_row(d20, "2026-10-19T12:00:00.0", 1190),
            ],
        )
        .metrics(
            "TrainingHistory",
            "20261001_20261028_1",
            vec![training_row(d20, "2026-10-20T12:00:00.0", "PRODUCTIVE")],
        )
        .entry(
            "DI_CONNECT/DI-Connect-Wellness/synthetic_sleepData.json",
            "[]",
        )
}
