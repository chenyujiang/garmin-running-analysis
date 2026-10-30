//! Seam 2: `runsync sync` after `runsync import-export`, both data sources
//! driven by in-memory fakes. What the export already holds is not asked
//! for again; only the last 7 days are refreshed as always.

mod common;

use chrono::{DateTime, TimeZone, Utc};
use tempfile::TempDir;

use common::export::{day, standard_package, utc};
use common::fake_metrics::FakeMetrics;
use common::fake_source::{FakeActivity, FakeSource};
use common::{runsync, stderr};
use runsync::data_dir::DataDir;
use runsync::source::{ActivitySource, GarminMetric, MetricsSource};
use runsync::sync::SyncOptions;
use runsync::sync_all::{Outcome, sync_all};

fn now() -> DateTime<Utc> {
    Utc.with_ymd_and_hms(2026, 10, 30, 12, 0, 0).unwrap()
}

/// A data directory with the standard package (exported 2026-10-28)
/// imported and a (fake) garminconnect token directory.
fn imported() -> (TempDir, DataDir) {
    let data = TempDir::new().unwrap();
    std::fs::copy(
        common::fixture_archive().join("config.toml"),
        data.path().join("config.toml"),
    )
    .unwrap();
    let downloads = TempDir::new().unwrap();
    let zip = downloads.path().join("export.zip");
    standard_package().write(&zip);
    let out = runsync(data.path(), &["import-export", zip.to_str().unwrap()]);
    assert!(
        out.status.success(),
        "import-export failed: {}",
        stderr(&out)
    );

    let data_dir = DataDir::open(data.path().to_path_buf()).unwrap();
    std::fs::create_dir_all(data_dir.garminconnect_token_dir()).unwrap();
    (data, data_dir)
}

#[test]
fn sync_after_an_import_asks_only_for_what_the_export_does_not_hold() {
    let (_data, data_dir) = imported();
    // 9001 is in the export and older than 7 days; 9100 is new.
    let mut personal = FakeSource::new(vec![
        FakeActivity::run(9100, utc(2026, 10, 29, 6, 0), "New"),
        FakeActivity::run(9001, utc(2026, 10, 20, 6, 0), "Exported"),
    ]);
    let mut metrics = FakeMetrics::new();
    let options = SyncOptions {
        now: now(),
        today: now().date_naive(),
        page_size: 100,
    };

    let report = sync_all(
        &data_dir,
        &options,
        Ok(&mut personal as &mut dyn ActivitySource),
        Some(&mut metrics as &mut dyn MetricsSource),
    );

    assert!(
        matches!(report.personal_api, Outcome::Done(_)),
        "{report:?}"
    );
    assert!(
        matches!(report.garminconnect, Outcome::Done(_)),
        "{report:?}"
    );
    assert_eq!(personal.detail_requests, vec![9100]);
    assert_eq!(personal.fit_requests, vec![9100]);
    // The export has daily summaries for 2026-10-01..=2026-10-28: the
    // refresh range is fetched, the next three full weeks are not, the
    // week reaching back before the export is.
    let daily = &personal.daily_requests;
    assert_eq!(daily[0], (day(2026, 10, 24), day(2026, 10, 30)));
    assert_eq!(daily[1], (day(2026, 9, 26), day(2026, 10, 2)));
    for covered in [
        (day(2026, 10, 17), day(2026, 10, 23)),
        (day(2026, 10, 10), day(2026, 10, 16)),
        (day(2026, 10, 3), day(2026, 10, 9)),
    ] {
        assert!(!daily.contains(&covered), "{covered:?} requested");
    }
    // Metrics: today's snapshot, then the Sundays back to the first
    // activity (2026-09-27); those within the export (10-04..10-25) are not
    // asked for.
    for metric in GarminMetric::ALL {
        assert_eq!(
            metrics.requested_dates(metric),
            vec![day(2026, 10, 30), day(2026, 9, 27)],
            "{metric:?}"
        );
    }
}
