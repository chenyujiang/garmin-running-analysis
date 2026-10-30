//! Rate-limit cooldown markers in `state/`.
//!
//! When a data source answers 429 or `CAPTCHA_REQUIRED`, `sync` writes
//! `state/<source>.cooldown.json` (`source`, `since_utc`, `until_utc`,
//! `reason`). For [`COOLDOWN_HOURS`] after that, `sync` skips the source and
//! says why and until when. Once the cooldown is over the marker is removed
//! and the source runs again; deleting the marker by hand lifts it early.

use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};

use crate::data_dir::DataDir;

pub const COOLDOWN_HOURS: i64 = 24;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Cooldown {
    pub source: String,
    #[serde(with = "utc_z")]
    pub since_utc: DateTime<Utc>,
    #[serde(with = "utc_z")]
    pub until_utc: DateTime<Utc>,
    pub reason: String,
}

/// `state/<source>.cooldown.json`.
pub fn marker_path(data_dir: &DataDir, source: &str) -> PathBuf {
    data_dir.state_dir().join(format!("{source}.cooldown.json"))
}

/// Start a cooldown for `source` at `now` and write its marker.
pub fn start(
    data_dir: &DataDir,
    source: &str,
    now: DateTime<Utc>,
    reason: &str,
) -> Result<Cooldown> {
    let cooldown = Cooldown {
        source: source.to_owned(),
        since_utc: now,
        until_utc: now + Duration::hours(COOLDOWN_HOURS),
        reason: reason.to_owned(),
    };
    let path = marker_path(data_dir, source);
    write(&path, &cooldown)
        .with_context(|| format!("writing cooldown marker {}", path.display()))?;
    Ok(cooldown)
}

/// The cooldown `source` is in at `now`, if any. An expired marker is
/// removed, so the source runs again.
pub fn active(data_dir: &DataDir, source: &str, now: DateTime<Utc>) -> Result<Option<Cooldown>> {
    let path = marker_path(data_dir, source);
    let text = match std::fs::read_to_string(&path) {
        Ok(text) => text,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(err) => {
            return Err(err).with_context(|| format!("reading cooldown marker {}", path.display()));
        }
    };
    let cooldown: Cooldown = serde_json::from_str(&text).with_context(|| {
        format!(
            "cooldown marker {} is unreadable; delete it to resume this source",
            path.display()
        )
    })?;
    if now >= cooldown.until_utc {
        std::fs::remove_file(&path)
            .with_context(|| format!("removing expired cooldown marker {}", path.display()))?;
        return Ok(None);
    }
    Ok(Some(cooldown))
}

fn write(path: &Path, cooldown: &Cooldown) -> Result<()> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir)?;
    }
    let part = path.with_extension("json.part");
    std::fs::write(&part, serde_json::to_string_pretty(cooldown)? + "\n")?;
    std::fs::rename(&part, path)?;
    Ok(())
}

/// Timestamps as `2026-10-30T12:00:00Z`, like the rest of the project.
mod utc_z {
    use chrono::{DateTime, SecondsFormat, Utc};
    use serde::{Deserialize, Deserializer, Serializer};

    pub fn serialize<S: Serializer>(t: &DateTime<Utc>, s: S) -> Result<S::Ok, S::Error> {
        s.serialize_str(&t.to_rfc3339_opts(SecondsFormat::Secs, true))
    }

    pub fn deserialize<'de, D: Deserializer<'de>>(d: D) -> Result<DateTime<Utc>, D::Error> {
        let text = String::deserialize(d)?;
        DateTime::parse_from_rfc3339(&text)
            .map(|t| t.with_timezone(&Utc))
            .map_err(serde::de::Error::custom)
    }
}
