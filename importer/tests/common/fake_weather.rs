//! An in-memory `WeatherSource` for Seam 2 tests: no HTTP. It records every
//! request and answers with a synthetic Open-Meteo archive response holding
//! one temperature per hour of the requested range.

use chrono::{Duration, NaiveDate};
use runsync::source::SourceError;
use runsync::weather::{WeatherRequest, WeatherSource};

#[derive(Default)]
pub struct FakeWeather {
    pub requests: Vec<WeatherRequest>,
    /// Fail every request with this error instead of answering.
    pub fail: Option<fn() -> SourceError>,
}

impl FakeWeather {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn failing(fail: fn() -> SourceError) -> Self {
        Self {
            fail: Some(fail),
            ..Self::default()
        }
    }
}

impl WeatherSource for FakeWeather {
    fn hourly_temperature(&mut self, request: &WeatherRequest) -> Result<String, SourceError> {
        self.requests.push(request.clone());
        if let Some(fail) = self.fail {
            return Err(fail());
        }
        Ok(response(request.start, request.end))
    }
}

/// Add an activity straight to the analysis database whose GPS records sit
/// at the given synthetic positions.
pub fn add_activity(
    data_dir: &runsync::data_dir::DataDir,
    activity_id: i64,
    activity_type: &str,
    start_utc: &str,
    positions: &[(f64, f64)],
) {
    let conn = runsync::db::open(&data_dir.analysis_db_path()).unwrap();
    conn.execute(
        "INSERT INTO activities (activity_id, activity_type, start_time_utc, start_time_local)
         VALUES (?1, ?2, ?3, ?3)",
        rusqlite::params![activity_id, activity_type, start_utc],
    )
    .unwrap();
    for (i, (lat, lon)) in positions.iter().enumerate() {
        conn.execute(
            "INSERT INTO records (activity_id, timestamp, lat, lon) VALUES (?1, ?2, ?3, ?4)",
            rusqlite::params![activity_id, format!("{start_utc}+{i:04}"), lat, lon],
        )
        .unwrap();
    }
}

/// An archive response shaped like Open-Meteo's for `timezone=GMT`. The
/// latitude/longitude it reports are a model grid point, not the request's.
pub fn response(start: NaiveDate, end: NaiveDate) -> String {
    let mut times = Vec::new();
    let mut temps = Vec::new();
    let mut day = start;
    while day <= end {
        for h in 0..24 {
            times.push(format!("{}T{h:02}:00", day.format("%Y-%m-%d")));
            temps.push(serde_json::json!(10.0 + f64::from(h) / 10.0));
        }
        day += Duration::days(1);
    }
    serde_json::json!({
        "latitude": 1.23,
        "longitude": 4.56,
        "generationtime_ms": 1.0,
        "utc_offset_seconds": 0,
        "timezone": "GMT",
        "timezone_abbreviation": "GMT",
        "elevation": 10.0,
        "hourly_units": {"time": "iso8601", "temperature_2m": "°C"},
        "hourly": {"time": times, "temperature_2m": temps}
    })
    .to_string()
}
