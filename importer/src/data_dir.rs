//! The data directory: `RUNNING_DATA_DIR`, default `%USERPROFILE%\running-data`.
//! Every path the importer touches is derived from here.

use std::path::{Path, PathBuf};

use anyhow::{Context, Result, bail};

use crate::config::Config;

pub const ENV_VAR: &str = "RUNNING_DATA_DIR";

#[derive(Debug, Clone)]
pub struct DataDir {
    root: PathBuf,
}

impl DataDir {
    /// Resolve the data directory from the environment and check it exists.
    pub fn from_env() -> Result<Self> {
        let root = match std::env::var_os(ENV_VAR) {
            Some(v) if !v.is_empty() => PathBuf::from(v),
            _ => default_root()?,
        };
        Self::open(root)
    }

    pub fn open(root: PathBuf) -> Result<Self> {
        if !root.is_dir() {
            bail!(
                "data directory {} does not exist. Create it, or set {ENV_VAR} to the \
                 directory that holds config.toml, raw/ and secrets/.",
                root.display()
            );
        }
        Ok(Self { root })
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn config_path(&self) -> PathBuf {
        self.root.join("config.toml")
    }

    pub fn analysis_db_path(&self) -> PathBuf {
        self.root.join("running.sqlite")
    }

    pub fn raw_dir(&self) -> PathBuf {
        self.root.join("raw")
    }

    /// `raw/personal_api/activities/`: `<activityId>.json` and `<activityId>.fit`.
    pub fn personal_api_activities_dir(&self) -> PathBuf {
        self.raw_dir().join("personal_api").join("activities")
    }

    pub fn load_config(&self) -> Result<Config> {
        Config::load(&self.config_path())
    }
}

fn default_root() -> Result<PathBuf> {
    let home = std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .context("neither RUNNING_DATA_DIR nor USERPROFILE is set")?;
    Ok(PathBuf::from(home).join("running-data"))
}
