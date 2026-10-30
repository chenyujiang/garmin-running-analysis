//! `runsync`: syncs Garmin data into the raw archive and builds the SQLite
//! analysis database from it. The binary in `main.rs` is a thin CLI over
//! these modules.

pub mod activity;
pub mod config;
pub mod data_dir;
pub mod db;
pub mod fit;
pub mod rebuild;
