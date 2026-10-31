//! Daily summaries (steps, stress etc.) from the Personal API.
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

/// `daily_wellness.resting_hr_bpm` from every source. The watch is worn in
/// the daytime only, so Garmin's resting heart rate is too high to use; the
/// analysis takes `hr_rest` from `config.toml`. The raw archive keeps
/// Garmin's value.
pub const RESTING_HR: SqlValue = SqlValue::Null;

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
    let n = |pointer: &str| sql_number(row.pointer(pointer));
    store_values(
        conn,
        date.calendar_date,
        [
            // heartRate.restingValue is not loaded, see RESTING_HR.
            RESTING_HR,
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

/// Insert or replace one `daily_wellness` row. `values` are the columns
/// after `calendar_date`, in table order (resting_hr_bpm ...
/// respiration_avg_brpm).
pub fn store_values(conn: &Connection, date: NaiveDate, values: [SqlValue; 14]) -> Result<()> {
    let mut params = vec![SqlValue::Text(date.format("%Y-%m-%d").to_string())];
    params.extend(values);
    conn.execute(
        "INSERT OR REPLACE INTO daily_wellness (
            calendar_date, resting_hr_bpm, min_hr_bpm, max_hr_bpm, steps, steps_distance_m,
            calories_total_kcal, calories_active_kcal, calories_resting_kcal,
            intensity_moderate_min, intensity_vigorous_min, stress_avg,
            body_battery_min, body_battery_max, respiration_avg_brpm
         ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15)",
        rusqlite::params_from_iter(params),
    )?;
    Ok(())
}

/// A JSON number as an SQL value: integers stay integers.
pub fn sql_number(value: Option<&Value>) -> SqlValue {
    match value {
        Some(Value::Number(x)) => match x.as_i64() {
            Some(i) => SqlValue::Integer(i),
            None => x.as_f64().map_or(SqlValue::Null, SqlValue::Real),
        },
        _ => SqlValue::Null,
    }
}
