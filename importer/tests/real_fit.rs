//! Parses the real FIT files in the data directory. Manual only:
//! `cargo test -- --ignored`. Read-only: it never runs `rebuild`, so the
//! real analysis database is untouched. It prints counts only, never
//! positions.

use runsync::data_dir::DataDir;
use runsync::fit::ActivityFit;

#[test]
#[ignore = "reads real FIT files from RUNNING_DATA_DIR; run with --ignored"]
fn real_fit_files_parse_into_plausible_records() {
    let data_dir = DataDir::from_env().expect("data directory");
    let dir = data_dir.personal_api_activities_dir();
    let mut files: Vec<_> = std::fs::read_dir(&dir)
        .expect("activities directory")
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.extension().is_some_and(|e| e.eq_ignore_ascii_case("fit")))
        .collect();
    files.sort();
    assert!(!files.is_empty(), "no FIT files in {}", dir.display());

    let (mut ok, mut failed, mut records, mut laps) = (0, 0, 0, 0);
    for path in &files {
        let bytes = std::fs::read(path).unwrap();
        match ActivityFit::parse(&bytes) {
            Ok(fit) => {
                ok += 1;
                records += fit.records.len();
                laps += fit.laps.len();
                for r in &fit.records {
                    assert!(r.timestamp_utc.ends_with('Z'));
                    if let Some(hr) = r.heart_rate {
                        assert!((20.0..=250.0).contains(&hr), "heart rate {hr}");
                    }
                    if let Some(v) = r.speed {
                        assert!((0.0..=15.0).contains(&v), "speed {v} m/s");
                    }
                    if let Some(lat) = r.lat {
                        assert!((-90.0..=90.0).contains(&lat), "lat out of range");
                    }
                    if let Some(lon) = r.lon {
                        assert!((-180.0..=180.0).contains(&lon), "lon out of range");
                    }
                }
            }
            Err(err) => {
                failed += 1;
                eprintln!("failed: {}: {err:#}", path.display());
            }
        }
    }
    eprintln!("{ok} parsed, {failed} failed, {records} records, {laps} laps");
    assert!(ok > 0, "no FIT file parsed");
    assert!(records > 0, "no records");
}
