//! `config.toml` in the data directory, shared with the Python analysis
//! package (which reads it with `tomllib`). Sections the importer does not
//! use yet are still parsed so a malformed file fails early.

use std::path::Path;

use anyhow::{Context, Result, bail};
use serde::Deserialize;

#[derive(Debug, Clone, Deserialize)]
pub struct Config {
    #[serde(default)]
    pub aerobic: Aerobic,
    #[serde(default)]
    pub physiology: Vec<Physiology>,
    #[serde(default)]
    pub sync: Sync,
}

/// `[sync]`: pacing for data source requests. Requests are sent one at a
/// time with this pause between them.
#[derive(Debug, Clone, Deserialize)]
pub struct Sync {
    #[serde(default = "default_personal_api_interval_s")]
    pub personal_api_interval_s: f64,
}

impl Default for Sync {
    fn default() -> Self {
        Self {
            personal_api_interval_s: default_personal_api_interval_s(),
        }
    }
}

fn default_personal_api_interval_s() -> f64 {
    1.5
}

#[derive(Debug, Clone, Deserialize)]
pub struct Aerobic {
    #[serde(default = "default_reference_hr")]
    pub reference_hr: u32,
}

impl Default for Aerobic {
    fn default() -> Self {
        Self {
            reference_hr: default_reference_hr(),
        }
    }
}

fn default_reference_hr() -> u32 {
    145
}

/// One set of physiology parameters, valid from `effective_from` onwards.
#[derive(Debug, Clone, Deserialize)]
pub struct Physiology {
    pub effective_from: toml::value::Datetime,
    pub hr_max: u32,
    pub hr_rest: u32,
    pub lthr: u32,
}

impl Config {
    pub fn load(path: &Path) -> Result<Self> {
        if !path.is_file() {
            bail!(
                "config file {} not found. Create config.toml in the data directory \
                 (see README for the format).",
                path.display()
            );
        }
        let text =
            std::fs::read_to_string(path).with_context(|| format!("reading {}", path.display()))?;
        toml::from_str(&text).with_context(|| format!("parsing {}", path.display()))
    }
}
