//! Daily summaries (resting heart rate etc.) from the Personal API.
//!
//! The source answers a date range with `{"data": [row, ...]}`, one row per
//! day that has data. The raw archive keeps one file per requested day,
//! `<YYYY-MM-DD>.json`, holding that day's row exactly as served, or `null`
//! when the response had no row for it. Each file maps to at most one row of
//! `daily_wellness`.

use anyhow::{Context, Result};
use chrono::NaiveDate;
use rusqlite::Connection;
use rusqlite::types::Value as SqlValue;
use serde::Deserialize;
use serde_json::Value;
use serde_json::value::RawValue;

/// Raw file content for a requested day without data.
pub const NO_DATA: &str = "null";

#[derive(Deserialize)]
struct Response<'a> {
    #[serde(borrow, default)]
    data: Vec<&'a RawValue>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct RowDate {
    calendar_date: NaiveDate,
}

/// Split a daily summaries response for `start..=end` into one raw file
/// content per day, in date order. Rows outside the range are ignored.
pub fn split_response(
    body: &str,
    start: NaiveDate,
    end: NaiveDate,
) -> Result<Vec<(NaiveDate, String)>> {
    let response: Response =
        serde_json::from_str(body).context("not a daily summaries response")?;
    let mut rows = std::collections::BTreeMap::new();
    for raw in response.data {
        let date: RowDate =
            serde_json::from_str(raw.get()).context("daily summary row without calendarDate")?;
        rows.insert(date.calendar_date, raw.get().to_owned());
    }
    Ok(start
        .iter_days()
        .take_while(|d| *d <= end)
        .map(|d| (d, rows.remove(&d).unwrap_or_else(|| NO_DATA.to_owned())))
        .collect())
}

/// Load one raw daily summary file into `daily_wellness` (insert or
/// replace). Returns whether a row was written; `null` writes nothing.
pub fn store_day(conn: &Connection, text: &str) -> Result<bool> {
    let row: Value = serde_json::from_str(text).context("not a daily summary JSON")?;
    if row.is_null() {
        return Ok(false);
    }
    let date: RowDate =
        serde_json::from_value(row.clone()).context("daily summary without calendarDate")?;
    let n = |pointer: &str| -> SqlValue {
        match row.pointer(pointer) {
            Some(Value::Number(x)) => match x.as_i64() {
                Some(i) => SqlValue::Integer(i),
                None => x.as_f64().map_or(SqlValue::Null, SqlValue::Real),
            },
            _ => SqlValue::Null,
        }
    };
    conn.execute(
        "INSERT OR REPLACE INTO daily_wellness (
            calendar_date, resting_hr_bpm, min_hr_bpm, max_hr_bpm, steps, steps_distance_m,
            calories_total_kcal, calories_active_kcal, calories_resting_kcal,
            intensity_moderate_min, intensity_vigorous_min, stress_avg,
            body_battery_min, body_battery_max, respiration_avg_brpm
         ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15)",
        rusqlite::params![
            date.calendar_date.format("%Y-%m-%d").to_string(),
            n("/heartRate/restingValue"),
            n("/heartRate/minValue"),
            n("/heartRate/maxValue"),
            n("/movement/steps/value"),
            n("/movement/steps/distanceInMeters"),
            n("/calories/burnedTotal"),
            n("/calories/burnedActive"),
            n("/calories/burnedResting"),
            n("/intensityMinutes/moderate"),
            n("/intensityMinutes/vigorous"),
            n("/stress/avgLevel"),
            n("/bodyBattery/minValue"),
            n("/bodyBattery/maxValue"),
            n("/respiration/avgValue"),
        ],
    )?;
    Ok(true)
}
