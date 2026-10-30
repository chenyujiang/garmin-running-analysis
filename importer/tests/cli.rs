//! The `sync` and `login` subcommands exist but are placeholders for now.

mod common;

use common::{data_dir_from_fixture, runsync, stdout};

#[test]
fn sync_says_it_is_not_implemented_yet() {
    let dir = data_dir_from_fixture();
    let out = runsync(dir.path(), &["sync"]);
    assert!(out.status.success());
    assert!(stdout(&out).contains("尚未实现"));
}

#[test]
fn login_says_it_is_not_implemented_yet() {
    let dir = data_dir_from_fixture();
    let out = runsync(dir.path(), &["login"]);
    assert!(out.status.success());
    assert!(stdout(&out).contains("尚未实现"));
}
