//! Loads the real Garmin account export package(s) archived under
//! `raw/export/` in the data directory. Manual only:
//! `cargo test -- --ignored`. Read-only: it loads into a database in a temp
//! directory, so the real analysis database is untouched. It prints counts
//! and date ranges only, never positions or the account's e-mail.

use runsync::data_dir::DataDir;
use runsync::export::{archived_packages, load_package};
use tempfile::TempDir;

#[test]
#[ignore = "reads the real export package from RUNNING_DATA_DIR; run with --ignored"]
fn the_real_export_package_loads_with_plausible_counts() {
    let data_dir = DataDir::from_env().expect("data directory");
    let packages = archived_packages(&data_dir).expect("listing raw/export");
    assert!(
        !packages.is_empty(),
        "no package in {}",
        data_dir.export_dir().display()
    );
    let scratch = TempDir::new().unwrap();
    let mut conn = runsync::db::open(&scratch.path().join("running.sqlite")).unwrap();

    for (_, path) in packages {
        let tx = conn.transaction().unwrap();
        let report = load_package(&tx, &data_dir, &path).expect("package loads");
        tx.commit().unwrap();
        eprint!("{report}");
        assert!(
            report.activities + report.kept_activities > 0,
            "no activities"
        );
        assert!(report.fit_activities > 0, "no activity FIT loaded");
        assert!(
            !report.daily_days.is_empty() || report.kept_daily > 0,
            "no daily summaries"
        );
    }
}
