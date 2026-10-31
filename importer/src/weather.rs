//! `runsync sync` for hourly air temperature from the Open-Meteo historical
//! weather archive, the third data source. The watch records no
//! temperature, so the analysis reads the weather at the usual running spot.
//!
//! - The grid point: for each road run (`running`, `street_running`) with GPS
//!   records, the median latitude and longitude, each rounded to 0.1°; the
//!   grid point that occurs most often is the main one. Without any GPS
//!   nothing is requested.
//! - The dates: the first road run's UTC date up to `today` minus
//!   [`ARCHIVE_LAG_DAYS`]. Days that already have a temperature for the main
//!   grid point are not asked for again; each run of consecutive missing
//!   days goes out as one request. A day whose hours are all NULL (the
//!   archive may not have the latest days yet) counts as missing.
//! - Each response is stored verbatim as `raw/open-meteo/<start>_<end>.json`,
//!   then `<start>_<end>.request.json` records the grid point and dates that
//!   were asked for (the response's coordinates are a model grid point, not
//!   the request's). A response without its request file is ignored.
//! - Responses are loaded into `hourly_weather` at once; `rebuild` loads all
//!   of them again ([`load_archive`]). A NULL never replaces a temperature.
//!
//! The grid point and coordinates only ever go to Open-Meteo and into the
//! data directory: never into output, logs or error messages. [`GridPoint`]
//! and [`WeatherRequest`] print redacted, and HTTP errors drop the URL.

use std::collections::{BTreeSet, HashMap};
use std::path::{Path, PathBuf};
use std::time::Duration as StdDuration;

use anyhow::{Context, Result, anyhow};
use chrono::{Duration, NaiveDate, NaiveDateTime, SecondsFormat};
use reqwest::StatusCode;
use reqwest::blocking::Client;
use rusqlite::{Connection, params};
use serde::{Deserialize, Serialize};

use crate::data_dir::DataDir;
use crate::db;
use crate::source::SourceError;
use crate::sync_support::{record_sync_run, utc_now_string, write_atomically};

pub const SOURCE_NAME: &str = "open_meteo";
pub const ARCHIVE_URL: &str = "https://archive-api.open-meteo.com/v1/archive";
/// Activity types whose GPS decides the grid point and whose first date
/// starts the range; the analysis package's `AEROBIC_TYPES`.
pub const ROAD_RUN_TYPES: [&str; 2] = ["running", "street_running"];
/// The archive lags behind: ask for days up to `today` minus this.
pub const ARCHIVE_LAG_DAYS: i64 = 2;

const HOURLY: &str = "temperature_2m";
const TIMEZONE: &str = "GMT";

/// A 0.1° grid point, kept in tenths of a degree so it compares exactly.
/// `Debug` is redacted.
#[derive(Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct GridPoint {
    lat_tenths: i32,
    lon_tenths: i32,
}

impl std::fmt::Debug for GridPoint {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("GridPoint(<redacted>)")
    }
}

impl GridPoint {
    /// The grid point `lat`, `lon` (degrees) rounds to.
    pub fn round(lat: f64, lon: f64) -> Self {
        Self {
            lat_tenths: (lat * 10.0).round() as i32,
            lon_tenths: (lon * 10.0).round() as i32,
        }
    }

    pub fn lat(self) -> f64 {
        f64::from(self.lat_tenths) / 10.0
    }

    pub fn lon(self) -> f64 {
        f64::from(self.lon_tenths) / 10.0
    }
}

/// One archive request: a grid point and an inclusive date range. `Debug`
/// is redacted.
#[derive(Clone, PartialEq, Eq)]
pub struct WeatherRequest {
    pub grid: GridPoint,
    pub start: NaiveDate,
    pub end: NaiveDate,
}

impl std::fmt::Debug for WeatherRequest {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "WeatherRequest(<redacted>, {}..={})",
            self.start, self.end
        )
    }
}

impl WeatherRequest {
    /// The query parameters, and the only data sent to Open-Meteo.
    pub fn query(&self) -> Vec<(&'static str, String)> {
        vec![
            ("latitude", format!("{:.1}", self.grid.lat())),
            ("longitude", format!("{:.1}", self.grid.lon())),
            ("start_date", self.start.format("%Y-%m-%d").to_string()),
            ("end_date", self.end.format("%Y-%m-%d").to_string()),
            ("hourly", HOURLY.to_owned()),
            ("timezone", TIMEZONE.to_owned()),
        ]
    }
}

/// The weather data source seam: the real one is [`OpenMeteoClient`],
/// tests use an in-memory fake.
pub trait WeatherSource {
    /// The archive response for `request`, exactly as served.
    fn hourly_temperature(&mut self, request: &WeatherRequest) -> Result<String, SourceError>;
}

#[derive(Debug, Default)]
pub struct WeatherSyncReport {
    /// Hours loaded from the new response.
    pub hours: usize,
    /// The date ranges requested, in order. On a failure, the last one is
    /// the range that failed.
    pub ranges: Vec<(NaiveDate, NaiveDate)>,
    /// No road run has GPS records, so there is no grid point.
    pub no_gps: bool,
    /// There is no analysis database yet, so nothing was looked at.
    pub no_database: bool,
    /// Set when the request failed; nothing was archived.
    pub stopped_by: Option<SourceError>,
}

/// Fetch the missing days for the main grid point, archive and load them.
/// The run is recorded in `sync_runs` either way.
pub fn sync_open_meteo(
    data_dir: &DataDir,
    source: &mut dyn WeatherSource,
    today: NaiveDate,
) -> Result<WeatherSyncReport> {
    let started_at = utc_now_string();
    let mut report = WeatherSyncReport::default();
    let db_path = data_dir.analysis_db_path();
    if !db_path.exists() {
        // No database, no road runs: nothing to ask for, nothing to create.
        report.no_database = true;
        return Ok(report);
    }
    let conn = db::open(&db_path)?;

    match missing_requests(&conn, today)? {
        None => report.no_gps = true,
        Some(requests) => {
            for request in requests {
                report.ranges.push((request.start, request.end));
                match fetch(&conn, data_dir, source, &request) {
                    Ok(hours) => report.hours += hours,
                    Err(err) => {
                        log::warn!("{SOURCE_NAME} sync stopped: {err}");
                        report.stopped_by = Some(err);
                        break;
                    }
                }
            }
        }
    }

    let outcome = if report.no_gps {
        "skipped"
    } else {
        report
            .stopped_by
            .as_ref()
            .map_or("ok", SourceError::outcome)
    };
    record_sync_run(&conn, SOURCE_NAME, &started_at, outcome)?;
    Ok(report)
}

/// One request per run of consecutive days without a temperature for the
/// main grid point; `None` when there is no grid point.
fn missing_requests(conn: &Connection, today: NaiveDate) -> Result<Option<Vec<WeatherRequest>>> {
    let Some(grid) = main_grid_point(conn)? else {
        return Ok(None);
    };
    let Some(first) = first_road_run_date(conn)? else {
        return Ok(None);
    };
    let last = today - Duration::days(ARCHIVE_LAG_DAYS);
    let have = days_with_temperature(conn, grid)?;
    let mut requests: Vec<WeatherRequest> = Vec::new();
    for day in days(first, last).filter(|d| !have.contains(d)) {
        match requests.last_mut() {
            Some(request) if request.end.succ_opt() == Some(day) => request.end = day,
            _ => requests.push(WeatherRequest {
                grid,
                start: day,
                end: day,
            }),
        }
    }
    Ok(Some(requests))
}

/// The UTC days with at least one non-NULL hour for `grid` in
/// `hourly_weather`.
fn days_with_temperature(conn: &Connection, grid: GridPoint) -> Result<BTreeSet<NaiveDate>> {
    let mut stmt = conn.prepare(
        "SELECT DISTINCT substr(time_utc, 1, 10) FROM hourly_weather
         WHERE CAST(round(grid_lat * 10) AS INTEGER) = ?1
           AND CAST(round(grid_lon * 10) AS INTEGER) = ?2
           AND temperature_c IS NOT NULL",
    )?;
    let rows = stmt.query_map(params![grid.lat_tenths, grid.lon_tenths], |r| {
        r.get::<_, String>(0)
    })?;
    rows.map(|day| {
        let day = day?;
        NaiveDate::parse_from_str(&day, "%Y-%m-%d").with_context(|| format!("hourly day {day:?}"))
    })
    .collect()
}

/// Request, archive and load one range. Returns the hours loaded.
fn fetch(
    conn: &Connection,
    data_dir: &DataDir,
    source: &mut dyn WeatherSource,
    request: &WeatherRequest,
) -> Result<usize, SourceError> {
    let json = source.hourly_temperature(request)?;
    let hours = parse_response(&json).context("the Open-Meteo response could not be read")?;
    archive(&data_dir.open_meteo_dir(), request, &json)?;
    store_hours(conn, request.grid, &hours)?;
    Ok(hours.len())
}

/// The most common 0.1° grid point of the road runs' median positions.
/// Ties go to the smaller grid point, so the choice is stable.
fn main_grid_point(conn: &Connection) -> Result<Option<GridPoint>> {
    let mut stmt = conn.prepare(&format!(
        "SELECT r.activity_id, r.lat, r.lon
         FROM records r JOIN activities a ON a.activity_id = r.activity_id
         WHERE a.activity_type IN ({}) AND r.lat IS NOT NULL AND r.lon IS NOT NULL",
        road_run_types_sql()
    ))?;
    let mut positions: HashMap<i64, (Vec<f64>, Vec<f64>)> = HashMap::new();
    let rows = stmt.query_map([], |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, f64>(1)?,
            r.get::<_, f64>(2)?,
        ))
    })?;
    for row in rows {
        let (id, lat, lon) = row?;
        let entry = positions.entry(id).or_default();
        entry.0.push(lat);
        entry.1.push(lon);
    }
    let mut counts: HashMap<GridPoint, usize> = HashMap::new();
    for (lats, lons) in positions.into_values() {
        *counts
            .entry(GridPoint::round(median(lats), median(lons)))
            .or_default() += 1;
    }
    Ok(counts
        .into_iter()
        .max_by(|(a, n), (b, m)| n.cmp(m).then(b.cmp(a)))
        .map(|(grid, _)| grid))
}

fn median(mut values: Vec<f64>) -> f64 {
    values.sort_by(f64::total_cmp);
    let mid = values.len() / 2;
    if values.len() % 2 == 1 {
        values[mid]
    } else {
        (values[mid - 1] + values[mid]) / 2.0
    }
}

fn first_road_run_date(conn: &Connection) -> Result<Option<NaiveDate>> {
    let first: Option<String> = conn.query_row(
        &format!(
            "SELECT min(substr(start_time_utc, 1, 10)) FROM activities
             WHERE activity_type IN ({})",
            road_run_types_sql()
        ),
        [],
        |r| r.get(0),
    )?;
    first
        .map(|d| NaiveDate::parse_from_str(&d, "%Y-%m-%d").context("first road run date"))
        .transpose()
}

fn road_run_types_sql() -> String {
    ROAD_RUN_TYPES
        .iter()
        .map(|t| format!("'{t}'"))
        .collect::<Vec<_>>()
        .join(", ")
}

fn days(start: NaiveDate, end: NaiveDate) -> impl Iterator<Item = NaiveDate> {
    start.iter_days().take_while(move |d| *d <= end)
}

/// The `<stem>.request.json` file next to each archived response.
#[derive(Serialize, Deserialize)]
struct RequestFile {
    latitude: f64,
    longitude: f64,
    start_date: NaiveDate,
    end_date: NaiveDate,
    hourly: String,
    timezone: String,
}

const REQUEST_SUFFIX: &str = ".request.json";

/// Every archived response with its request, oldest name first.
fn archived_requests(dir: &Path) -> Result<Vec<(PathBuf, WeatherRequest)>> {
    if !dir.is_dir() {
        return Ok(Vec::new());
    }
    let mut found = Vec::new();
    for entry in std::fs::read_dir(dir).with_context(|| format!("listing {}", dir.display()))? {
        let path = entry?.path();
        let Some(stem) = path
            .file_name()
            .and_then(|n| n.to_str())
            .and_then(|n| n.strip_suffix(REQUEST_SUFFIX))
        else {
            continue;
        };
        let response = dir.join(format!("{stem}.json"));
        if !response.is_file() {
            continue;
        }
        let file: RequestFile = std::fs::read_to_string(&path)
            .map_err(anyhow::Error::from)
            .and_then(|t| Ok(serde_json::from_str(&t)?))
            .with_context(|| format!("reading {}", path.display()))?;
        let request = WeatherRequest {
            grid: GridPoint::round(file.latitude, file.longitude),
            start: file.start_date,
            end: file.end_date,
        };
        found.push((response, request));
    }
    found.sort_by(|a, b| a.0.cmp(&b.0));
    Ok(found)
}

/// Write the response, then its request file; both atomically. A name that
/// is taken (another grid point, same dates) gets a `-<n>` suffix.
fn archive(dir: &Path, request: &WeatherRequest, json: &str) -> Result<()> {
    std::fs::create_dir_all(dir).with_context(|| format!("creating {}", dir.display()))?;
    let base = format!("{}_{}", request.start, request.end);
    let stem = (1..)
        .map(|n| {
            if n == 1 {
                base.clone()
            } else {
                format!("{base}-{n}")
            }
        })
        .find(|stem| {
            !dir.join(format!("{stem}.json")).exists()
                && !dir.join(format!("{stem}{REQUEST_SUFFIX}")).exists()
        })
        .expect("some name is free");
    write_atomically(&dir.join(format!("{stem}.json")), json.as_bytes())?;
    let file = RequestFile {
        latitude: request.grid.lat(),
        longitude: request.grid.lon(),
        start_date: request.start,
        end_date: request.end,
        hourly: HOURLY.to_owned(),
        timezone: TIMEZONE.to_owned(),
    };
    write_atomically(
        &dir.join(format!("{stem}{REQUEST_SUFFIX}")),
        (serde_json::to_string_pretty(&file)? + "\n").as_bytes(),
    )
}

#[derive(Deserialize)]
struct Response {
    #[serde(default)]
    utc_offset_seconds: i64,
    hourly: Hourly,
}

#[derive(Deserialize)]
struct Hourly {
    time: Vec<String>,
    temperature_2m: Vec<Option<f64>>,
}

/// `(time_utc, temperature_c)` per hour of a response.
fn parse_response(json: &str) -> Result<Vec<(String, Option<f64>)>> {
    let response: Response = serde_json::from_str(json).context("not an archive response")?;
    if response.utc_offset_seconds != 0 {
        anyhow::bail!("times are not GMT");
    }
    let Hourly {
        time,
        temperature_2m,
    } = response.hourly;
    if time.len() != temperature_2m.len() {
        anyhow::bail!("time and temperature_2m differ in length");
    }
    time.into_iter()
        .zip(temperature_2m)
        .map(|(t, temp)| {
            let t = NaiveDateTime::parse_from_str(&t, "%Y-%m-%dT%H:%M")
                .with_context(|| format!("hourly time {t:?}"))?;
            Ok((t.and_utc().to_rfc3339_opts(SecondsFormat::Secs, true), temp))
        })
        .collect()
}

fn store_hours(conn: &Connection, grid: GridPoint, hours: &[(String, Option<f64>)]) -> Result<()> {
    // A NULL (no value yet) never replaces a temperature.
    let mut stmt = conn.prepare_cached(
        "INSERT INTO hourly_weather (grid_lat, grid_lon, time_utc, temperature_c)
         VALUES (?1, ?2, ?3, ?4)
         ON CONFLICT (grid_lat, grid_lon, time_utc) DO UPDATE
         SET temperature_c = coalesce(excluded.temperature_c, hourly_weather.temperature_c)",
    )?;
    for (time, temp) in hours {
        stmt.execute(params![grid.lat(), grid.lon(), time, temp])?;
    }
    Ok(())
}

/// Load every archived response in `raw/open-meteo/` into `hourly_weather`
/// (for `rebuild`). Returns the hours loaded and the responses skipped.
pub fn load_archive(conn: &Connection, data_dir: &DataDir) -> Result<(usize, usize)> {
    let mut hours = 0;
    let mut skipped = 0;
    for (path, request) in archived_requests(&data_dir.open_meteo_dir())? {
        let loaded = std::fs::read_to_string(&path)
            .map_err(anyhow::Error::from)
            .and_then(|text| parse_response(&text))
            .and_then(|rows| {
                store_hours(conn, request.grid, &rows)?;
                Ok(rows.len())
            });
        match loaded {
            Ok(n) => hours += n,
            Err(err) => {
                log::warn!("skipping {}: {err:#}", path.display());
                skipped += 1;
            }
        }
    }
    Ok((hours, skipped))
}

/// The real [`WeatherSource`]: one GET to the Open-Meteo archive per
/// request, no key. Building it does not touch the network.
pub struct OpenMeteoClient {
    http: Client,
    url: String,
}

impl OpenMeteoClient {
    pub fn new() -> Result<Self> {
        Self::with_url(ARCHIVE_URL)
    }

    /// A client for another endpoint (tests).
    pub fn with_url(url: &str) -> Result<Self> {
        let http = Client::builder()
            .user_agent(concat!("runsync/", env!("CARGO_PKG_VERSION")))
            .timeout(StdDuration::from_secs(120))
            .build()
            .context("building HTTP client")?;
        Ok(Self {
            http,
            url: url.to_owned(),
        })
    }
}

impl WeatherSource for OpenMeteoClient {
    fn hourly_temperature(&mut self, request: &WeatherRequest) -> Result<String, SourceError> {
        let url = reqwest::Url::parse_with_params(&self.url, request.query())
            .map_err(|_| SourceError::Other(anyhow!("Open-Meteo: invalid archive URL")))?;
        let response = self.http.get(url).send().map_err(request_error)?;
        let status = response.status();
        if status == StatusCode::TOO_MANY_REQUESTS {
            return Err(SourceError::RateLimited("HTTP 429 from Open-Meteo".into()));
        }
        if !status.is_success() {
            return Err(SourceError::Other(anyhow!("HTTP {status} from Open-Meteo")));
        }
        response.text().map_err(request_error)
    }
}

/// The URL holds the grid point: drop it from the error.
fn request_error(err: reqwest::Error) -> SourceError {
    let kind = if err.is_timeout() {
        "timed out"
    } else if err.is_connect() {
        "could not connect"
    } else if err.is_decode() || err.is_body() {
        "could not read the response"
    } else {
        "request failed"
    };
    SourceError::Other(anyhow::Error::new(err.without_url()).context(format!("Open-Meteo: {kind}")))
}
