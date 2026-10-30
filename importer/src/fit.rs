//! Activity FIT files (`raw/personal_api/activities/<activityId>.fit`) into
//! the `records` and `laps` tables. Only `record` and `lap` messages are
//! read; everything else, including private `unknown_*` messages, is
//! ignored.

use std::collections::HashSet;

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use fitparser::de::{DecodeOption, from_bytes_with_options};
use fitparser::profile::MesgNum;
use fitparser::{FitDataField, FitDataRecord, Value};
use rusqlite::{Connection, params};

/// One `records` row. Units are SI; see `migrations/0003_records_laps.sql`.
#[derive(Debug, Clone, PartialEq)]
pub struct Record {
    pub timestamp_utc: String,
    pub heart_rate: Option<f64>,
    pub speed: Option<f64>,
    pub cadence: Option<f64>,
    pub altitude: Option<f64>,
    pub distance: Option<f64>,
    pub lat: Option<f64>,
    pub lon: Option<f64>,
    pub power: Option<f64>,
    pub temperature: Option<f64>,
}

/// One `laps` row.
#[derive(Debug, Clone, PartialEq)]
pub struct Lap {
    pub start_time_utc: Option<String>,
    pub end_time_utc: Option<String>,
    pub elapsed_duration_s: Option<f64>,
    pub timer_duration_s: Option<f64>,
    pub distance_m: Option<f64>,
    pub avg_speed_mps: Option<f64>,
    pub max_speed_mps: Option<f64>,
    pub avg_hr_bpm: Option<f64>,
    pub max_hr_bpm: Option<f64>,
    pub avg_cadence: Option<f64>,
    pub max_cadence: Option<f64>,
    pub avg_power_w: Option<f64>,
    pub elevation_gain_m: Option<f64>,
    pub elevation_loss_m: Option<f64>,
}

/// The parts of one activity FIT file that go into the analysis database.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct ActivityFit {
    /// `file_id.type`, e.g. `activity` or `monitoring_b`.
    pub file_type: Option<String>,
    /// `start_time` of the first `session` message.
    pub session_start: Option<DateTime<Utc>>,
    pub records: Vec<Record>,
    pub laps: Vec<Lap>,
}

impl ActivityFit {
    /// Parse a whole FIT file. Fails if the file cannot be decoded at all
    /// (bad CRC, truncated, fitparser issue #58, ...).
    pub fn parse(bytes: &[u8]) -> Result<Self> {
        let options: HashSet<DecodeOption> = [DecodeOption::DropUnknownMessages].into();
        let messages = from_bytes_with_options(bytes, &options).context("decoding FIT")?;
        let mut fit = ActivityFit::default();
        for msg in &messages {
            match msg.kind() {
                MesgNum::Record => {
                    if let Some(r) = record(msg) {
                        fit.records.push(r);
                    }
                }
                MesgNum::Lap => fit.laps.push(lap(msg)),
                MesgNum::FileId if fit.file_type.is_none() => {
                    fit.file_type = file_type(msg.fields());
                }
                MesgNum::Session if fit.session_start.is_none() => {
                    if let Some(Value::Timestamp(t)) = find(msg.fields(), "start_time") {
                        fit.session_start = Some(t.with_timezone(&Utc));
                    }
                }
                _ => {}
            }
        }
        Ok(fit)
    }

    pub fn is_activity(&self) -> bool {
        self.file_type.as_deref() == Some("activity")
    }

    /// [`store`](Self::store) inside a savepoint: on error nothing from this
    /// file is left in the database.
    pub fn store_or_nothing(&self, conn: &Connection, activity_id: i64) -> Result<()> {
        conn.execute_batch("SAVEPOINT fit_file")?;
        match self.store(conn, activity_id) {
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

    /// Replace this activity's rows in `records` and `laps`.
    pub fn store(&self, conn: &Connection, activity_id: i64) -> Result<()> {
        conn.execute("DELETE FROM records WHERE activity_id = ?1", [activity_id])?;
        conn.execute("DELETE FROM laps WHERE activity_id = ?1", [activity_id])?;
        let mut insert = conn.prepare(
            "INSERT OR REPLACE INTO records (activity_id, timestamp, heart_rate, speed, cadence,
                 altitude, distance, lat, lon, power, temperature)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)",
        )?;
        for r in &self.records {
            insert.execute(params![
                activity_id,
                r.timestamp_utc,
                r.heart_rate,
                r.speed,
                r.cadence,
                r.altitude,
                r.distance,
                r.lat,
                r.lon,
                r.power,
                r.temperature,
            ])?;
        }
        let mut insert = conn.prepare(
            "INSERT INTO laps (activity_id, lap_index, start_time_utc, end_time_utc,
                 elapsed_duration_s, timer_duration_s, distance_m, avg_speed_mps, max_speed_mps,
                 avg_hr_bpm, max_hr_bpm, avg_cadence, max_cadence, avg_power_w,
                 elevation_gain_m, elevation_loss_m)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16)",
        )?;
        for (i, l) in self.laps.iter().enumerate() {
            insert.execute(params![
                activity_id,
                i as i64,
                l.start_time_utc,
                l.end_time_utc,
                l.elapsed_duration_s,
                l.timer_duration_s,
                l.distance_m,
                l.avg_speed_mps,
                l.max_speed_mps,
                l.avg_hr_bpm,
                l.max_hr_bpm,
                l.avg_cadence,
                l.max_cadence,
                l.avg_power_w,
                l.elevation_gain_m,
                l.elevation_loss_m,
            ])?;
        }
        Ok(())
    }
}

/// A `record` message; `None` if it has no timestamp.
fn record(msg: &FitDataRecord) -> Option<Record> {
    let f = msg.fields();
    Some(Record {
        timestamp_utc: timestamp(f, "timestamp")?,
        heart_rate: number(f, "heart_rate"),
        speed: number(f, "enhanced_speed").or_else(|| number(f, "speed")),
        cadence: number(f, "cadence"),
        altitude: number(f, "enhanced_altitude").or_else(|| number(f, "altitude")),
        distance: number(f, "distance"),
        lat: number(f, "position_lat").map(semicircles_to_degrees),
        lon: number(f, "position_long").map(semicircles_to_degrees),
        power: number(f, "power"),
        temperature: number(f, "temperature"),
    })
}

fn lap(msg: &FitDataRecord) -> Lap {
    let f = msg.fields();
    Lap {
        start_time_utc: timestamp(f, "start_time"),
        end_time_utc: timestamp(f, "timestamp"),
        elapsed_duration_s: number(f, "total_elapsed_time"),
        timer_duration_s: number(f, "total_timer_time"),
        distance_m: number(f, "total_distance"),
        avg_speed_mps: number(f, "enhanced_avg_speed").or_else(|| number(f, "avg_speed")),
        max_speed_mps: number(f, "enhanced_max_speed").or_else(|| number(f, "max_speed")),
        avg_hr_bpm: number(f, "avg_heart_rate"),
        max_hr_bpm: number(f, "max_heart_rate"),
        avg_cadence: number(f, "avg_cadence"),
        max_cadence: number(f, "max_cadence"),
        avg_power_w: number(f, "avg_power"),
        elevation_gain_m: number(f, "total_ascent"),
        elevation_loss_m: number(f, "total_descent"),
    }
}

/// `file_id.type` as fitparser names it; a value it has no name for as its
/// number.
fn file_type(fields: &[FitDataField]) -> Option<String> {
    match find(fields, "type")? {
        Value::String(s) => Some(s.clone()),
        _ => number(fields, "type").map(|n| n.to_string()),
    }
}

fn find<'a>(fields: &'a [FitDataField], name: &str) -> Option<&'a Value> {
    fields.iter().find(|f| f.name() == name).map(|f| f.value())
}

/// A numeric field with the profile's scale and offset applied.
fn number(fields: &[FitDataField], name: &str) -> Option<f64> {
    match find(fields, name)? {
        Value::Timestamp(_) | Value::String(_) | Value::Array(_) | Value::Invalid => None,
        v => v.clone().try_into().ok(),
    }
}

fn timestamp(fields: &[FitDataField], name: &str) -> Option<String> {
    match find(fields, name)? {
        Value::Timestamp(t) => Some(
            t.with_timezone(&Utc)
                .format("%Y-%m-%dT%H:%M:%SZ")
                .to_string(),
        ),
        _ => None,
    }
}

fn semicircles_to_degrees(s: f64) -> f64 {
    s * 180.0 / 2f64.powi(31)
}
