//! Activity summaries from the Personal API detail JSON
//! (`raw/personal_api/activities/<activityId>.json`) into the `activities` table.

use anyhow::{Context, Result};
use chrono::NaiveDateTime;
use rusqlite::{Connection, params};
use serde::Deserialize;

/// The typed columns of one `activities` row. Units are SI.
#[derive(Debug, Clone, PartialEq)]
pub struct Activity {
    pub activity_id: i64,
    pub activity_type: String,
    pub activity_name: Option<String>,
    /// `YYYY-MM-DDTHH:MM:SSZ`
    pub start_time_utc: String,
    /// `YYYY-MM-DDTHH:MM:SS`, wall clock at the activity's location.
    pub start_time_local: String,
    pub time_zone: Option<String>,
    pub distance_m: Option<f64>,
    pub duration_s: Option<f64>,
    pub moving_duration_s: Option<f64>,
    pub elapsed_duration_s: Option<f64>,
    pub avg_speed_mps: Option<f64>,
    pub max_speed_mps: Option<f64>,
    pub avg_hr_bpm: Option<f64>,
    pub max_hr_bpm: Option<f64>,
    pub elevation_gain_m: Option<f64>,
    pub elevation_loss_m: Option<f64>,
    pub calories_kcal: Option<f64>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct DetailJson {
    activity_id: i64,
    activity_name: Option<String>,
    #[serde(rename = "activityTypeDTO")]
    activity_type: TypeDto,
    #[serde(rename = "timeZoneUnitDTO")]
    time_zone_unit: Option<TimeZoneDto>,
    #[serde(rename = "summaryDTO")]
    summary: SummaryDto,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct TypeDto {
    type_key: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct TimeZoneDto {
    time_zone: Option<String>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct SummaryDto {
    start_time_local: String,
    #[serde(rename = "startTimeGMT")]
    start_time_gmt: String,
    distance: Option<f64>,
    duration: Option<f64>,
    moving_duration: Option<f64>,
    elapsed_duration: Option<f64>,
    average_speed: Option<f64>,
    max_speed: Option<f64>,
    #[serde(rename = "averageHR")]
    average_hr: Option<f64>,
    #[serde(rename = "maxHR")]
    max_hr: Option<f64>,
    elevation_gain: Option<f64>,
    elevation_loss: Option<f64>,
    calories: Option<f64>,
}

impl Activity {
    /// Parse a Personal API activity detail JSON document.
    pub fn from_detail_json(text: &str) -> Result<Self> {
        let d: DetailJson = serde_json::from_str(text).context("not an activity detail JSON")?;
        let s = d.summary;
        Ok(Self {
            activity_id: d.activity_id,
            activity_type: d.activity_type.type_key,
            activity_name: d.activity_name,
            start_time_utc: format!("{}Z", normalize_timestamp(&s.start_time_gmt)?),
            start_time_local: normalize_timestamp(&s.start_time_local)?,
            time_zone: d.time_zone_unit.and_then(|t| t.time_zone),
            distance_m: s.distance,
            duration_s: s.duration,
            moving_duration_s: s.moving_duration,
            elapsed_duration_s: s.elapsed_duration,
            avg_speed_mps: s.average_speed,
            max_speed_mps: s.max_speed,
            avg_hr_bpm: s.average_hr,
            max_hr_bpm: s.max_hr,
            elevation_gain_m: s.elevation_gain,
            elevation_loss_m: s.elevation_loss,
            calories_kcal: s.calories,
        })
    }

    /// Insert or replace this activity's row.
    pub fn upsert(&self, conn: &Connection) -> Result<()> {
        conn.execute(
            "INSERT OR REPLACE INTO activities (
                activity_id, activity_type, activity_name, start_time_utc, start_time_local,
                time_zone, distance_m, duration_s, moving_duration_s, elapsed_duration_s,
                avg_speed_mps, max_speed_mps, avg_hr_bpm, max_hr_bpm,
                elevation_gain_m, elevation_loss_m, calories_kcal
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17)",
            params![
                self.activity_id,
                self.activity_type,
                self.activity_name,
                self.start_time_utc,
                self.start_time_local,
                self.time_zone,
                self.distance_m,
                self.duration_s,
                self.moving_duration_s,
                self.elapsed_duration_s,
                self.avg_speed_mps,
                self.max_speed_mps,
                self.avg_hr_bpm,
                self.max_hr_bpm,
                self.elevation_gain_m,
                self.elevation_loss_m,
                self.calories_kcal,
            ],
        )?;
        Ok(())
    }
}

/// Garmin writes `2026-10-07T22:08:46.0`; store whole seconds, `2026-10-07T22:08:46`.
fn normalize_timestamp(raw: &str) -> Result<String> {
    let t = NaiveDateTime::parse_from_str(raw, "%Y-%m-%dT%H:%M:%S%.f")
        .or_else(|_| NaiveDateTime::parse_from_str(raw, "%Y-%m-%d %H:%M:%S%.f"))
        .with_context(|| format!("unrecognised timestamp {raw:?}"))?;
    Ok(t.format("%Y-%m-%dT%H:%M:%S").to_string())
}
