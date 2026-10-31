//! Open-Meteo hourly air temperature: which grid point and dates `sync`
//! asks for (Seam 2, fake source), how responses are archived under
//! `raw/open-meteo/`, and how `sync` and `rebuild` load them into
//! `hourly_weather` (Seam 1). All coordinates are synthetic.

mod common;

use chrono::NaiveDate;
use tempfile::TempDir;

use common::fake_weather::{FakeWeather, add_activity};
use runsync::data_dir::DataDir;
use runsync::weather::{WeatherSyncReport, sync_open_meteo};

fn date(y: i32, m: u32, d: u32) -> NaiveDate {
    NaiveDate::from_ymd_opt(y, m, d).unwrap()
}

fn data_dir() -> (TempDir, DataDir) {
    let dir = TempDir::new().unwrap();
    std::fs::write(dir.path().join("config.toml"), "").unwrap();
    let data_dir = DataDir::open(dir.path().to_path_buf()).unwrap();
    (dir, data_dir)
}

fn sync(data_dir: &DataDir, weather: &mut FakeWeather, today: NaiveDate) -> WeatherSyncReport {
    sync_open_meteo(data_dir, weather, today).unwrap()
}

fn query(start: &str, end: &str) -> Vec<(&'static str, String)> {
    vec![
        ("latitude", "10.0".into()),
        ("longitude", "20.0".into()),
        ("start_date", start.into()),
        ("end_date", end.into()),
        ("hourly", "temperature_2m".into()),
        ("timezone", "GMT".into()),
    ]
}

/// Two road runs round to (10.0, 20.0), one to (10.5, 20.5); the trail run
/// and the rides are elsewhere and do not count.
fn usual_runs(data_dir: &DataDir) {
    add_activity(
        data_dir,
        1,
        "running",
        "2026-10-01T06:00:00Z",
        &[(10.01, 20.04), (10.02, 19.98), (9.99, 20.01)],
    );
    add_activity(
        data_dir,
        2,
        "street_running",
        "2026-10-05T06:00:00Z",
        &[(10.04, 20.02)],
    );
    add_activity(
        data_dir,
        3,
        "running",
        "2026-10-08T06:00:00Z",
        &[(10.48, 20.51)],
    );
    add_activity(
        data_dir,
        4,
        "trail_running",
        "2026-09-01T06:00:00Z",
        &[(30.5, 40.5)],
    );
    add_activity(
        data_dir,
        5,
        "cycling",
        "2026-09-02T06:00:00Z",
        &[(30.5, 40.5)],
    );
    add_activity(
        data_dir,
        6,
        "cycling",
        "2026-09-03T06:00:00Z",
        &[(30.5, 40.5)],
    );
}

#[test]
fn the_first_sync_asks_for_every_day_from_the_first_run_at_the_most_common_grid_point() {
    let (_dir, data_dir) = data_dir();
    usual_runs(&data_dir);
    let mut weather = FakeWeather::new();

    let report = sync(&data_dir, &mut weather, date(2026, 10, 30));

    assert_eq!(weather.requests.len(), 1);
    assert_eq!(
        weather.requests[0].query(),
        query("2026-10-01", "2026-10-28")
    );
    assert_eq!(report.hours, 28 * 24);
    assert_eq!(report.range, Some((date(2026, 10, 1), date(2026, 10, 28))));
    assert!(report.stopped_by.is_none());
}

#[test]
fn a_later_sync_asks_only_for_the_new_days_and_none_when_nothing_is_missing() {
    let (_dir, data_dir) = data_dir();
    usual_runs(&data_dir);
    let mut weather = FakeWeather::new();
    sync(&data_dir, &mut weather, date(2026, 10, 30));

    sync(&data_dir, &mut weather, date(2026, 11, 2));
    let report = sync(&data_dir, &mut weather, date(2026, 11, 2));

    assert_eq!(weather.requests.len(), 2);
    assert_eq!(
        weather.requests[1].query(),
        query("2026-10-29", "2026-10-31")
    );
    assert_eq!(report.range, None);
    assert_eq!(report.hours, 0);
    assert_eq!(hourly_rows(&data_dir).len(), 31 * 24);
}

#[test]
fn without_gps_on_any_road_run_nothing_is_requested() {
    let (_dir, data_dir) = data_dir();
    add_activity(&data_dir, 1, "running", "2026-10-01T06:00:00Z", &[]);
    add_activity(
        &data_dir,
        2,
        "cycling",
        "2026-10-02T06:00:00Z",
        &[(10.0, 20.0)],
    );
    let mut weather = FakeWeather::new();

    let report = sync(&data_dir, &mut weather, date(2026, 10, 30));

    assert!(report.no_gps);
    assert!(weather.requests.is_empty());
}

#[test]
fn the_response_is_archived_verbatim_with_the_requested_grid_point_and_dates() {
    let (_dir, data_dir) = data_dir();
    usual_runs(&data_dir);
    // The cache left by ticket 19 records no grid point: ignored.
    let dir = data_dir.open_meteo_dir();
    std::fs::create_dir_all(&dir).unwrap();
    std::fs::write(
        dir.join("hourly_temperature_2m_2026-10-01_2026-10-28.json"),
        common::fake_weather::response(date(2026, 10, 1), date(2026, 10, 28)),
    )
    .unwrap();
    let mut weather = FakeWeather::new();

    sync(&data_dir, &mut weather, date(2026, 10, 30));

    assert_eq!(weather.requests.len(), 1, "the old cache is not reused");
    let response = std::fs::read_to_string(dir.join("2026-10-01_2026-10-28.json")).unwrap();
    assert_eq!(
        response,
        common::fake_weather::response(date(2026, 10, 1), date(2026, 10, 28))
    );
    let request: serde_json::Value = serde_json::from_str(
        &std::fs::read_to_string(dir.join("2026-10-01_2026-10-28.request.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(request["latitude"], 10.0);
    assert_eq!(request["longitude"], 20.0);
    assert_eq!(request["start_date"], "2026-10-01");
    assert_eq!(request["end_date"], "2026-10-28");
}

#[test]
fn when_the_main_grid_point_moves_only_the_new_one_is_requested_and_the_old_archive_stays() {
    let (_dir, data_dir) = data_dir();
    usual_runs(&data_dir);
    let mut weather = FakeWeather::new();
    sync(&data_dir, &mut weather, date(2026, 10, 30));
    // Three more runs at (10.5, 20.5) make it the main grid point.
    for id in 7..=9 {
        add_activity(
            &data_dir,
            id,
            "running",
            "2026-10-20T06:00:00Z",
            &[(10.5, 20.5)],
        );
    }

    sync(&data_dir, &mut weather, date(2026, 10, 30));

    assert_eq!(weather.requests.len(), 2);
    let query = weather.requests[1].query();
    assert_eq!(query[0], ("latitude", "10.5".to_owned()));
    assert_eq!(query[1], ("longitude", "20.5".to_owned()));
    assert_eq!(query[2], ("start_date", "2026-10-01".to_owned()));
    assert_eq!(query[3], ("end_date", "2026-10-28".to_owned()));
    assert_eq!(
        hourly_rows(&data_dir).len(),
        2 * 28 * 24,
        "both grid points are kept"
    );
}

#[test]
fn sync_loads_one_row_per_grid_point_and_hour_with_utc_times() {
    let (_dir, data_dir) = data_dir();
    usual_runs(&data_dir);

    sync(&data_dir, &mut FakeWeather::new(), date(2026, 10, 30));

    let rows = hourly_rows(&data_dir);
    assert_eq!(rows.len(), 28 * 24);
    assert_eq!(
        rows[0],
        (10.0, 20.0, "2026-10-01T00:00:00Z".to_owned(), Some(10.0))
    );
    assert_eq!(rows[23].2, "2026-10-01T23:00:00Z");
    assert!((rows[23].3.unwrap() - 12.3).abs() < 1e-9);
}

#[test]
fn rebuild_loads_the_archive_to_the_same_rows_as_sync() {
    let (_dir, data_dir) = data_dir();
    usual_runs(&data_dir);
    let mut weather = FakeWeather::new();
    sync(&data_dir, &mut weather, date(2026, 10, 30));
    sync(&data_dir, &mut weather, date(2026, 11, 2));
    let after_sync = hourly_rows(&data_dir);

    let report = runsync::rebuild::rebuild(&data_dir).unwrap();

    assert_eq!(report.weather_hours, 31 * 24);
    assert_eq!(hourly_rows(&data_dir), after_sync);
}

#[test]
fn rebuild_keeps_one_row_per_grid_point_and_hour_when_responses_overlap() {
    let (_dir, data_dir) = data_dir();
    let dir = data_dir.open_meteo_dir();
    std::fs::create_dir_all(&dir).unwrap();
    for (stem, start, end) in [
        (
            "2026-10-01_2026-10-03",
            date(2026, 10, 1),
            date(2026, 10, 3),
        ),
        (
            "2026-10-03_2026-10-04",
            date(2026, 10, 3),
            date(2026, 10, 4),
        ),
    ] {
        std::fs::write(
            dir.join(format!("{stem}.json")),
            common::fake_weather::response(start, end),
        )
        .unwrap();
        std::fs::write(
            dir.join(format!("{stem}.request.json")),
            serde_json::json!({
                "latitude": 10.0, "longitude": 20.0,
                "start_date": start.to_string(), "end_date": end.to_string(),
                "hourly": "temperature_2m", "timezone": "GMT"
            })
            .to_string(),
        )
        .unwrap();
    }

    runsync::rebuild::rebuild(&data_dir).unwrap();

    assert_eq!(hourly_rows(&data_dir).len(), 4 * 24);
}

/// A one-shot HTTP server on loopback answering every request with
/// `status`. Returns its base URL.
fn stub_server(status: &'static str) -> String {
    use std::io::{Read, Write};
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}/v1/archive", listener.local_addr().unwrap());
    std::thread::spawn(move || {
        if let Ok((mut stream, _)) = listener.accept() {
            let mut buf = [0u8; 4096];
            let _ = stream.read(&mut buf);
            let _ = write!(
                stream,
                "HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            );
        }
    });
    url
}

/// A loopback URL nothing listens on.
fn closed_port() -> String {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    drop(listener);
    format!("http://{addr}/v1/archive")
}

#[test]
fn errors_from_the_real_client_name_neither_the_grid_point_nor_the_url() {
    use runsync::sync::SyncOptions;
    use runsync::sync_all::sync_all;
    use runsync::weather::OpenMeteoClient;

    for url in [
        stub_server("500 Internal Server Error"),
        stub_server("429 Too Many Requests"),
        closed_port(),
    ] {
        let (_dir, data_dir) = data_dir();
        usual_runs(&data_dir);
        let mut client = OpenMeteoClient::with_url(&url).unwrap();
        let now = chrono::TimeZone::with_ymd_and_hms(&chrono::Utc, 2026, 10, 30, 12, 0, 0).unwrap();
        let options = SyncOptions {
            now,
            today: now.date_naive(),
            page_size: 100,
        };

        let report = sync_all(
            &data_dir,
            &options,
            Err(anyhow::anyhow!("no key")),
            None,
            &mut client,
        );

        let runsync::sync_all::Outcome::Failed(text) = &report.open_meteo else {
            panic!("expected a failure, got {:?}", report.open_meteo);
        };
        assert!(text.starts_with("open_meteo: "), "{text}");
        for leak in ["10.0", "20.0", "latitude", "longitude", "http", "127.0.0.1"] {
            assert!(!text.contains(leak), "{leak} in {text}");
        }
    }
}

fn hourly_rows(data_dir: &DataDir) -> Vec<(f64, f64, String, Option<f64>)> {
    let conn = runsync::db::open(&data_dir.analysis_db_path()).unwrap();
    let mut stmt = conn
        .prepare(
            "SELECT grid_lat, grid_lon, time_utc, temperature_c FROM hourly_weather
             ORDER BY grid_lat, grid_lon, time_utc",
        )
        .unwrap();
    stmt.query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)))
        .unwrap()
        .map(Result::unwrap)
        .collect()
}
