//! CLI behaviour that needs no network: `sync` without a key or token.

mod common;

use common::{data_dir_from_fixture, runsync, stderr, stdout};

#[test]
fn sync_without_a_personal_api_key_says_where_to_put_it() {
    let dir = data_dir_from_fixture();
    let out = runsync(dir.path(), &["sync"]);
    assert!(!out.status.success());
    let err = stderr(&out);
    assert!(err.contains("personal_api.key"), "{err}");
    assert!(!dir.path().join("running.sqlite").exists());
}

#[test]
fn sync_with_an_empty_key_file_is_refused() {
    let dir = data_dir_from_fixture();
    std::fs::create_dir_all(dir.path().join("secrets")).unwrap();
    std::fs::write(dir.path().join("secrets/personal_api.key"), "  \n").unwrap();
    let out = runsync(dir.path(), &["sync"]);
    assert!(!out.status.success());
    assert!(stderr(&out).contains("empty"), "{}", stderr(&out));
}

/// A fresh cooldown marker skips the Personal API before its key is even
/// needed; with no garminconnect token either, the sync has nothing to do.
#[test]
fn sync_skips_a_source_in_cooldown_and_says_until_when() {
    let dir = data_dir_from_fixture();
    let since = chrono::Utc::now();
    let until = since + chrono::Duration::hours(24);
    let fmt = |t: chrono::DateTime<chrono::Utc>| t.format("%Y-%m-%dT%H:%M:%SZ").to_string();
    std::fs::create_dir_all(dir.path().join("state")).unwrap();
    std::fs::write(
        dir.path().join("state/personal_api.cooldown.json"),
        format!(
            r#"{{"source":"personal_api","since_utc":"{}","until_utc":"{}","reason":"rate limited (HTTP 429)"}}"#,
            fmt(since),
            fmt(until)
        ),
    )
    .unwrap();

    let out = runsync(dir.path(), &["sync"]);

    assert!(out.status.success(), "{}", stderr(&out));
    let text = stdout(&out);
    assert!(
        text.contains("personal_api: skipped, rate limited (HTTP 429)"),
        "{text}"
    );
    assert!(text.contains("cooling down until"), "{text}");
    assert!(!dir.path().join("running.sqlite").exists());
}

/// `runsync login` itself is interactive and talks to Garmin, so it is not
/// run here.
#[test]
fn sync_without_a_garminconnect_token_skips_it_and_says_how_to_enable_it() {
    let dir = data_dir_from_fixture();
    let out = runsync(dir.path(), &["sync"]);
    assert!(!out.status.success(), "the personal_api key is missing");
    let out = stdout(&out);
    assert!(out.contains("garminconnect: skipped"), "{out}");
    assert!(out.contains("runsync login"), "{out}");
}
