//! Shared helpers for the integration tests: a temp data directory built
//! from the hand-written fixture archive, and a way to run the binary in it.

#![allow(dead_code)]

pub mod fake_source;
pub mod fit;

use std::path::{Path, PathBuf};
use std::process::{Command, Output};

use tempfile::TempDir;

pub fn fixture_archive() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/archive")
}

/// A fresh temp data directory holding a copy of the fixture archive.
pub fn data_dir_from_fixture() -> TempDir {
    let dir = TempDir::new().unwrap();
    copy_dir(&fixture_archive(), dir.path());
    dir
}

fn copy_dir(from: &Path, to: &Path) {
    std::fs::create_dir_all(to).unwrap();
    for entry in std::fs::read_dir(from).unwrap() {
        let entry = entry.unwrap();
        let target = to.join(entry.file_name());
        if entry.file_type().unwrap().is_dir() {
            copy_dir(&entry.path(), &target);
        } else {
            std::fs::copy(entry.path(), &target).unwrap();
        }
    }
}

/// Run `runsync <args>` with `RUNNING_DATA_DIR` pointing at `data_dir`.
pub fn runsync(data_dir: &Path, args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_runsync"))
        .args(args)
        .env("RUNNING_DATA_DIR", data_dir)
        .env_remove("RUST_LOG")
        .output()
        .unwrap()
}

pub fn stderr(out: &Output) -> String {
    String::from_utf8_lossy(&out.stderr).into_owned()
}

pub fn stdout(out: &Output) -> String {
    String::from_utf8_lossy(&out.stdout).into_owned()
}
