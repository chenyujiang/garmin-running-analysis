//! `runsync sync` as a whole: the Personal API, then garminconnect, one after
//! the other and independent of each other. A source that is rate limited
//! gets a cooldown marker (see [`crate::cooldown`]) and is skipped until it
//! expires; rejected credentials end with the fix for that source. Nothing
//! here asks for a password.

use chrono::{DateTime, Local, Utc};

use crate::cooldown::{self, Cooldown};
use crate::data_dir::DataDir;
use crate::garmin_metrics::{self, MetricsSyncOptions, sync_garmin_metrics};
use crate::source::{ActivitySource, MetricsSource, SourceError};
use crate::sync::{self, SyncOptions, sync_activities};

/// Where to get a new Personal API key.
pub const PERSONAL_API_KEY_URL: &str = "https://connect.garmin.com/app/settings/personalApiToken";

/// What happened to one source. Each carries a one-line, user-facing message
/// that starts with the source name.
#[derive(Debug)]
pub enum Outcome {
    Done(String),
    /// Not run, and that is expected (cooldown, no garminconnect token).
    Skipped(String),
    Failed(String),
}

impl Outcome {
    pub fn message(&self) -> &str {
        match self {
            Outcome::Done(m) | Outcome::Skipped(m) | Outcome::Failed(m) => m,
        }
    }
}

#[derive(Debug)]
pub struct SyncAllReport {
    pub personal_api: Outcome,
    pub garminconnect: Outcome,
}

impl SyncAllReport {
    /// False when either source failed.
    pub fn success(&self) -> bool {
        !matches!(self.personal_api, Outcome::Failed(_))
            && !matches!(self.garminconnect, Outcome::Failed(_))
    }
}

/// Sync both sources. `personal_api` is `Err` when the client could not be
/// built (e.g. no key file); `garminconnect` is `None` when there is no token
/// yet. Building either must not touch the network.
pub fn sync_all(
    data_dir: &DataDir,
    options: &SyncOptions,
    personal_api: anyhow::Result<&mut dyn ActivitySource>,
    garminconnect: Option<&mut dyn MetricsSource>,
) -> SyncAllReport {
    let personal_api = guarded(data_dir, sync::SOURCE_NAME, options.now, || {
        let source = personal_api.map_err(|err| format!("{}: {err:#}", sync::SOURCE_NAME))?;
        run_personal_api(data_dir, source, options)
    });
    let garminconnect = guarded(data_dir, garmin_metrics::SOURCE_NAME, options.now, || {
        let Some(source) = garminconnect else {
            return Ok(Outcome::Skipped(format!(
                "{}: skipped, no token in {}. Run `runsync login` once to enable it.",
                garmin_metrics::SOURCE_NAME,
                data_dir.garminconnect_token_dir().display()
            )));
        };
        run_garminconnect(data_dir, source, options)
    });
    SyncAllReport {
        personal_api,
        garminconnect,
    }
}

/// What a source run ends with when it stopped on a [`SourceError`].
enum Stop {
    /// The cooldown reason and what was done before the stop.
    RateLimited {
        reason: String,
        summary: String,
    },
    Message(String),
}

type RunResult = Result<Outcome, Stop>;

impl From<String> for Stop {
    fn from(message: String) -> Self {
        Stop::Message(message)
    }
}

/// Skip the source while it is cooling down; start a cooldown when it
/// reports a rate limit.
fn guarded(
    data_dir: &DataDir,
    source: &str,
    now: DateTime<Utc>,
    run: impl FnOnce() -> RunResult,
) -> Outcome {
    match cooldown::active(data_dir, source, now) {
        Ok(Some(cooldown)) => return Outcome::Skipped(cooling_down(&cooldown)),
        Ok(None) => {}
        Err(err) => return Outcome::Failed(format!("{source}: {err:#}")),
    }
    match run() {
        Ok(outcome) => outcome,
        Err(Stop::Message(message)) => Outcome::Failed(message),
        Err(Stop::RateLimited { reason, summary }) => {
            match cooldown::start(data_dir, source, now, &reason) {
                Ok(cooldown) => Outcome::Failed(format!(
                    "{source}: {reason} after {summary}; stopped without retrying. Syncs skip {source} for {} h, \
                     until {}. Delete {} to try sooner.",
                    cooldown::COOLDOWN_HOURS,
                    local(cooldown.until_utc),
                    cooldown::marker_path(data_dir, source).display()
                )),
                Err(err) => Outcome::Failed(format!(
                    "{source}: {reason} after {summary}; stopped without retrying, but the cooldown marker \
                     could not be written: {err:#}"
                )),
            }
        }
    }
}

fn cooling_down(cooldown: &Cooldown) -> String {
    format!(
        "{source}: skipped, {reason} at {since}; cooling down until {until}.",
        source = cooldown.source,
        reason = cooldown.reason,
        since = local(cooldown.since_utc),
        until = local(cooldown.until_utc),
    )
}

fn local(t: DateTime<Utc>) -> String {
    t.with_timezone(&Local)
        .format("%Y-%m-%d %H:%M %:z")
        .to_string()
}

fn run_personal_api(
    data_dir: &DataDir,
    source: &mut dyn ActivitySource,
    options: &SyncOptions,
) -> RunResult {
    let name = sync::SOURCE_NAME;
    let report =
        sync_activities(data_dir, source, options).map_err(|err| format!("{name}: {err:#}"))?;
    let summary = format!(
        "{} new activities, {} refreshed, {} FIT files, {} daily summary days,          {} files could not be parsed",
        report.new_activities,
        report.refreshed_activities,
        report.fit_files,
        report.daily_summaries,
        report.unparsable
    );
    finish(name, summary, report.stopped_by, || {
        format!(
            "the Personal API key was rejected; it may have expired (keys last about two years,              the current one until about 2027-10). Generate a new key at              {PERSONAL_API_KEY_URL} and save it to {}.",
            data_dir.personal_api_key_path().display()
        )
    })
}

fn run_garminconnect(
    data_dir: &DataDir,
    source: &mut dyn MetricsSource,
    options: &SyncOptions,
) -> RunResult {
    let name = garmin_metrics::SOURCE_NAME;
    let metrics_options = MetricsSyncOptions {
        today: options.today,
    };
    let report = sync_garmin_metrics(data_dir, source, &metrics_options)
        .map_err(|err| format!("{name}: {err:#}"))?;
    let summary = format!(
        "{} metric responses, {} could not be parsed",
        report.fetched, report.unparsable
    );
    finish(name, summary, report.stopped_by, || {
        "the token is missing, expired or was rejected. Run `runsync login` to log in again."
            .to_owned()
    })
}

/// The outcome of a source run that ended normally or on a [`SourceError`].
/// Only the fix for rejected credentials differs between sources.
fn finish(
    name: &str,
    summary: String,
    stopped_by: Option<SourceError>,
    credentials_fix: impl FnOnce() -> String,
) -> RunResult {
    match stopped_by {
        None => Ok(Outcome::Done(format!("{name}: {summary}"))),
        Some(SourceError::RateLimited(reason)) => Err(Stop::RateLimited {
            reason: format!("rate limited ({reason})"),
            summary,
        }),
        Some(SourceError::CredentialsRejected) => {
            Err(Stop::Message(format!("{name}: {}", credentials_fix())))
        }
        Some(SourceError::Other(err)) => Err(Stop::Message(format!(
            "{name}: stopped after {summary}: {err:#}. Run `runsync sync` again to resume              where it stopped."
        ))),
    }
}
