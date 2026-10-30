//! `runsync`: syncs Garmin data into the raw archive and builds the SQLite
//! analysis database from it. The binary in `main.rs` is a thin CLI over
//! these modules.

pub mod activity;
pub mod config;
pub mod cooldown;
pub mod daily;
pub mod data_dir;
pub mod db;
pub mod export;
pub mod fit;
pub mod garmin_metrics;
pub mod garminconnect;
pub mod personal_api;
pub mod rebuild;
pub mod source;
pub mod sync;
pub mod sync_all;
