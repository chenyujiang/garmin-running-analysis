//! Seam 2: `runsync sync` as a whole, all three data sources driven by
//! in-memory fakes. Covers the rate-limit cooldown in `state/`, the sources
//! being independent, and the hint shown when credentials are rejected.

mod common;

use chrono::{DateTime, Duration, TimeZone, Utc};
use tempfile::TempDir;

use common::fake_metrics::FakeMetrics;
use common::fake_source::{Failure, FakeActivity, FakeSource};
use common::fake_weather::{FakeWeather, add_activity};
use runsync::data_dir::DataDir;
use runsync::source::SourceError;
use runsync::source::{ActivitySource, GarminMetric, MetricsSource};
use runsync::sync::SyncOptions;
use runsync::sync_all::{Outcome, SyncAllReport, sync_all};

fn now() -> DateTime<Utc> {
    Utc.with_ymd_and_hms(2026, 10, 30, 12, 0, 0).unwrap()
}

fn options_at(now: DateTime<Utc>) -> SyncOptions {
    SyncOptions {
        now,
        today: now.date_naive(),
        page_size: 100,
    }
}

/// An empty data directory with a (fake) garminconnect token directory, so
/// both sources run.
fn data_dir() -> (TempDir, DataDir) {
    let dir = TempDir::new().unwrap();
    std::fs::write(dir.path().join("config.toml"), "").unwrap();
    let data_dir = DataDir::open(dir.path().to_path_buf()).unwrap();
    std::fs::create_dir_all(data_dir.garminconnect_token_dir()).unwrap();
    (dir, data_dir)
}

fn activities() -> FakeSource {
    FakeSource::new(vec![FakeActivity::run(
        101,
        now() - Duration::days(3),
        "Easy",
    )])
}

fn rate_limited_activities() -> FakeSource {
    activities().failing_detail(101, Failure::RateLimited)
}

fn run(
    data_dir: &DataDir,
    now: DateTime<Utc>,
    personal: &mut FakeSource,
    metrics: &mut FakeMetrics,
) -> SyncAllReport {
    run_with_weather(data_dir, now, personal, metrics, &mut FakeWeather::new())
}

fn run_with_weather(
    data_dir: &DataDir,
    now: DateTime<Utc>,
    personal: &mut FakeSource,
    metrics: &mut FakeMetrics,
    weather: &mut FakeWeather,
) -> SyncAllReport {
    sync_all(
        data_dir,
        &options_at(now),
        Ok(personal as &mut dyn ActivitySource),
        Some(metrics as &mut dyn MetricsSource),
        weather,
    )
}

/// A road run with GPS, so Open-Meteo has a grid point to ask for.
fn with_gps(data_dir: &DataDir) {
    add_activity(
        data_dir,
        1,
        "running",
        "2026-10-01T06:00:00Z",
        &[(10.01, 20.02)],
    );
}

#[test]
fn a_failing_open_meteo_does_not_affect_the_other_sources() {
    let (_dir, data_dir) = data_dir();
    with_gps(&data_dir);
    let mut weather = FakeWeather::failing(|| SourceError::Other(anyhow::anyhow!("HTTP 500")));

    let report = run_with_weather(
        &data_dir,
        now(),
        &mut activities(),
        &mut FakeMetrics::new(),
        &mut weather,
    );

    assert!(
        matches!(report.personal_api, Outcome::Done(_)),
        "{report:?}"
    );
    assert!(
        matches!(report.garminconnect, Outcome::Done(_)),
        "{report:?}"
    );
    let Outcome::Failed(text) = &report.open_meteo else {
        panic!("expected a failure, got {:?}", report.open_meteo);
    };
    assert!(text.starts_with("open_meteo: "), "{text}");
    assert!(!report.success());
    assert_eq!(weather.requests.len(), 1);
}

#[test]
fn a_rate_limited_open_meteo_cools_down_alone_and_is_skipped_within_24_hours() {
    let (_dir, data_dir) = data_dir();
    with_gps(&data_dir);
    let mut weather = FakeWeather::failing(|| SourceError::RateLimited("HTTP 429".into()));
    let report = run_with_weather(
        &data_dir,
        now(),
        &mut activities(),
        &mut FakeMetrics::new(),
        &mut weather,
    );
    assert!(message(&report.open_meteo).contains("24 h"), "{report:?}");
    assert!(
        data_dir
            .state_dir()
            .join("open_meteo.cooldown.json")
            .is_file()
    );
    assert!(
        !data_dir
            .state_dir()
            .join("personal_api.cooldown.json")
            .exists()
    );

    let mut weather = FakeWeather::new();
    let report = run_with_weather(
        &data_dir,
        now() + Duration::hours(23),
        &mut activities(),
        &mut FakeMetrics::new(),
        &mut weather,
    );

    assert!(
        matches!(report.open_meteo, Outcome::Skipped(_)),
        "{report:?}"
    );
    assert!(weather.requests.is_empty());
    assert!(
        matches!(report.personal_api, Outcome::Done(_)),
        "{report:?}"
    );
    assert!(report.success());
}

#[test]
fn open_meteo_reports_hours_and_dates_but_no_coordinates() {
    let (_dir, data_dir) = data_dir();
    with_gps(&data_dir);

    let report = run(&data_dir, now(), &mut activities(), &mut FakeMetrics::new());

    let Outcome::Done(text) = &report.open_meteo else {
        panic!("expected done, got {:?}", report.open_meteo);
    };
    assert!(text.contains("672 hours"), "{text}");
    assert!(text.contains("2026-10-01"), "{text}");
    assert!(text.contains("2026-10-28"), "{text}");
    assert!(!text.contains("10.0") && !text.contains("20.0"), "{text}");
}

#[test]
fn without_gps_open_meteo_is_skipped_with_a_note() {
    let (_dir, data_dir) = data_dir();

    let report = run(&data_dir, now(), &mut activities(), &mut FakeMetrics::new());

    assert!(
        matches!(report.open_meteo, Outcome::Skipped(_)),
        "{report:?}"
    );
    assert!(message(&report.open_meteo).contains("GPS"));
    assert!(report.success());
}

fn message(outcome: &Outcome) -> &str {
    match outcome {
        Outcome::Done(m) | Outcome::Skipped(m) | Outcome::Failed(m) => m,
    }
}

#[test]
fn a_rate_limit_writes_a_cooldown_marker_with_time_and_reason() {
    let (_dir, data_dir) = data_dir();
    let mut personal = rate_limited_activities();

    let report = run(&data_dir, now(), &mut personal, &mut FakeMetrics::new());

    assert!(matches!(report.personal_api, Outcome::Failed(_)));
    assert!(!report.success());
    let text = message(&report.personal_api);
    assert!(text.contains("rate limited"), "{text}");
    assert!(text.contains("24 h"), "{text}");
    // Stopped at once: the detail was asked for once, nothing after it.
    assert_eq!(personal.detail_requests, vec![101]);
    assert!(personal.daily_requests.is_empty());

    let marker = data_dir.state_dir().join("personal_api.cooldown.json");
    let json: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(&marker).unwrap()).unwrap();
    assert_eq!(json["source"], "personal_api");
    assert_eq!(json["since_utc"], "2026-10-30T12:00:00Z");
    assert_eq!(json["until_utc"], "2026-10-31T12:00:00Z");
    assert!(json["reason"].as_str().unwrap().contains("rate limited"));
    // The other source has no marker.
    assert!(
        !data_dir
            .state_dir()
            .join("garminconnect.cooldown.json")
            .exists()
    );
}

#[test]
fn within_24_hours_the_rate_limited_source_is_skipped_with_reason_and_resume_time() {
    let (_dir, data_dir) = data_dir();
    run(
        &data_dir,
        now(),
        &mut rate_limited_activities(),
        &mut FakeMetrics::new(),
    );

    let mut personal = activities();
    let later = now() + Duration::hours(23);
    let report = run(&data_dir, later, &mut personal, &mut FakeMetrics::new());

    let Outcome::Skipped(text) = &report.personal_api else {
        panic!("expected a skip, got {:?}", report.personal_api);
    };
    assert!(text.contains("rate limited (HTTP 429)"), "{text}");
    assert!(text.contains("until"), "{text}");
    assert!(
        personal.list_requests.is_empty(),
        "no request while cooling down"
    );
    assert!(report.success(), "a cooldown skip is not a failure");
    assert!(matches!(report.garminconnect, Outcome::Done(_)));
}

#[test]
fn after_24_hours_the_source_runs_again_and_the_marker_is_gone() {
    let (_dir, data_dir) = data_dir();
    run(
        &data_dir,
        now(),
        &mut rate_limited_activities(),
        &mut FakeMetrics::new(),
    );

    let mut personal = activities();
    let later = now() + Duration::hours(24);
    let report = run(&data_dir, later, &mut personal, &mut FakeMetrics::new());

    assert!(
        matches!(report.personal_api, Outcome::Done(_)),
        "{report:?}"
    );
    assert_eq!(personal.detail_requests, vec![101]);
    assert!(
        data_dir
            .personal_api_activities_dir()
            .join("101.json")
            .exists()
    );
    assert!(
        !data_dir
            .state_dir()
            .join("personal_api.cooldown.json")
            .exists()
    );
}

#[test]
fn a_captcha_on_garminconnect_cools_down_only_garminconnect() {
    let (_dir, data_dir) = data_dir();
    let mut metrics = FakeMetrics::new().failing(
        GarminMetric::Vo2Max,
        now().date_naive(),
        Failure::RateLimited,
    );

    let report = run(&data_dir, now(), &mut activities(), &mut metrics);

    assert!(matches!(report.personal_api, Outcome::Done(_)));
    assert!(matches!(report.garminconnect, Outcome::Failed(_)));
    assert!(
        data_dir
            .state_dir()
            .join("garminconnect.cooldown.json")
            .exists()
    );
    assert!(
        !data_dir
            .state_dir()
            .join("personal_api.cooldown.json")
            .exists()
    );

    // Next run: garminconnect skipped without a request, personal_api runs.
    let mut metrics = FakeMetrics::new();
    let mut personal = activities();
    let report = run(
        &data_dir,
        now() + Duration::hours(1),
        &mut personal,
        &mut metrics,
    );
    assert!(matches!(report.garminconnect, Outcome::Skipped(_)));
    assert!(metrics.requests.is_empty());
    assert!(matches!(report.personal_api, Outcome::Done(_)));
    assert!(!personal.list_requests.is_empty());
}

#[test]
fn a_failing_personal_api_does_not_stop_garminconnect() {
    let (_dir, data_dir) = data_dir();
    let mut personal = activities().failing_detail(101, Failure::Other);
    let mut metrics = FakeMetrics::new();

    let report = run(&data_dir, now(), &mut personal, &mut metrics);

    assert!(matches!(report.personal_api, Outcome::Failed(_)));
    assert!(
        matches!(report.garminconnect, Outcome::Done(_)),
        "{report:?}"
    );
    assert!(!metrics.requests.is_empty());
    assert!(!report.success());
    // Other errors are not rate limits: no cooldown.
    assert!(
        !data_dir
            .state_dir()
            .join("personal_api.cooldown.json")
            .exists()
    );
}

#[test]
fn a_missing_personal_api_key_does_not_stop_garminconnect() {
    let (_dir, data_dir) = data_dir();
    let mut metrics = FakeMetrics::new();

    let report = sync_all(
        &data_dir,
        &options_at(now()),
        Err(anyhow::anyhow!("no key in secrets/personal_api.key")),
        Some(&mut metrics as &mut dyn MetricsSource),
        &mut FakeWeather::new(),
    );

    assert!(message(&report.personal_api).contains("personal_api.key"));
    assert!(matches!(report.personal_api, Outcome::Failed(_)));
    assert!(matches!(report.garminconnect, Outcome::Done(_)));
    assert!(!metrics.requests.is_empty());
}

#[test]
fn a_failing_garminconnect_does_not_undo_the_personal_api_sync() {
    let (_dir, data_dir) = data_dir();
    let mut metrics = FakeMetrics::new().failing(
        GarminMetric::TrainingStatus,
        now().date_naive(),
        Failure::Other,
    );

    let report = run(&data_dir, now(), &mut activities(), &mut metrics);

    assert!(matches!(report.personal_api, Outcome::Done(_)));
    assert!(matches!(report.garminconnect, Outcome::Failed(_)));
    assert!(
        data_dir
            .personal_api_activities_dir()
            .join("101.json")
            .exists()
    );
}

#[test]
fn a_rejected_personal_api_key_says_to_generate_a_new_one() {
    let (_dir, data_dir) = data_dir();
    let mut personal = activities().failing_detail(101, Failure::CredentialsRejected);

    let report = run(&data_dir, now(), &mut personal, &mut FakeMetrics::new());

    let text = message(&report.personal_api);
    assert!(matches!(report.personal_api, Outcome::Failed(_)));
    assert!(text.contains("new key"), "{text}");
    assert!(text.contains("2027-10"), "{text}");
    assert!(text.contains("personal_api.key"), "{text}");
    assert!(!text.contains("runsync login"), "{text}");
    assert!(
        !data_dir
            .state_dir()
            .join("personal_api.cooldown.json")
            .exists()
    );
}

#[test]
fn an_expired_garminconnect_token_says_to_run_login() {
    let (_dir, data_dir) = data_dir();
    let mut metrics = FakeMetrics::new().failing(
        GarminMetric::TrainingStatus,
        now().date_naive(),
        Failure::CredentialsRejected,
    );

    let report = run(&data_dir, now(), &mut activities(), &mut metrics);

    let text = message(&report.garminconnect);
    assert!(matches!(report.garminconnect, Outcome::Failed(_)));
    assert!(text.contains("runsync login"), "{text}");
    assert!(
        !data_dir
            .state_dir()
            .join("garminconnect.cooldown.json")
            .exists()
    );
}

#[test]
fn without_a_garminconnect_token_it_is_skipped_with_the_login_hint() {
    let (_dir, data_dir) = data_dir();

    let report = sync_all(
        &data_dir,
        &options_at(now()),
        Ok(&mut activities() as &mut dyn ActivitySource),
        None,
        &mut FakeWeather::new(),
    );

    assert!(matches!(report.garminconnect, Outcome::Skipped(_)));
    assert!(message(&report.garminconnect).contains("runsync login"));
    assert!(report.success());
}

#[test]
fn an_unreadable_cooldown_marker_stops_only_that_source() {
    let (_dir, data_dir) = data_dir();
    std::fs::create_dir_all(data_dir.state_dir()).unwrap();
    std::fs::write(data_dir.state_dir().join("personal_api.cooldown.json"), "{").unwrap();
    let mut personal = activities();

    let report = run(&data_dir, now(), &mut personal, &mut FakeMetrics::new());

    assert!(matches!(report.personal_api, Outcome::Failed(_)));
    assert!(message(&report.personal_api).contains("delete it"));
    assert!(personal.list_requests.is_empty());
    assert!(matches!(report.garminconnect, Outcome::Done(_)));
}
