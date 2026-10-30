use std::time::Duration;

use anyhow::{Result, bail};
use clap::{Parser, Subcommand};

use runsync::config::Config;
use runsync::data_dir::DataDir;
use runsync::garmin_metrics::{MetricsSyncOptions, sync_garmin_metrics};
use runsync::garminconnect::GarminConnectScript;
use runsync::personal_api::{ApiKey, PersonalApiClient};
use runsync::source::SourceError;
use runsync::sync::{SyncOptions, sync_activities};

/// Sync Garmin data into the raw archive and build the analysis database.
///
/// The data directory comes from RUNNING_DATA_DIR (default
/// %USERPROFILE%\running-data). Log verbosity follows RUST_LOG.
#[derive(Parser)]
#[command(name = "runsync", version)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Fetch new and recently changed data from Garmin.
    Sync,
    /// Log in to garminconnect interactively and store its token under secrets/.
    Login,
    /// Delete the analysis database and recreate it from the raw archive (offline).
    Rebuild,
}

fn main() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();
    if let Err(err) = run(Cli::parse()) {
        eprintln!("error: {err:#}");
        std::process::exit(1);
    }
}

fn run(cli: Cli) -> Result<()> {
    let data_dir = DataDir::from_env()?;
    let config = data_dir.load_config()?;
    match cli.command {
        Command::Sync => sync(&data_dir, &config),
        Command::Login => {
            let token_dir = data_dir.garminconnect_token_dir();
            runsync::garminconnect::login(&token_dir)?;
            println!("garminconnect token stored in {}", token_dir.display());
            Ok(())
        }
        Command::Rebuild => {
            let report = runsync::rebuild::rebuild(&data_dir)?;
            println!(
                "rebuilt {}: {} activities, {} FIT files, {} Garmin metric files, {} files skipped",
                data_dir.analysis_db_path().display(),
                report.activities,
                report.fit_files,
                report.garmin_metrics,
                report.skipped
            );
            Ok(())
        }
    }
}

/// Both sources run on every sync; one failing does not stop the other.
fn sync(data_dir: &DataDir, config: &Config) -> Result<()> {
    let personal = sync_personal_api(data_dir, config);
    if let Err(err) = &personal {
        eprintln!("error: {err:#}");
    }
    let metrics = sync_garminconnect(data_dir, config);
    match (personal, metrics) {
        (Ok(()), metrics) => metrics,
        (Err(_), Ok(())) => bail!("personal_api sync failed (see above)"),
        (Err(_), Err(err)) => Err(err.context("personal_api sync failed too (see above)")),
    }
}

fn sync_garminconnect(data_dir: &DataDir, config: &Config) -> Result<()> {
    let token_dir = data_dir.garminconnect_token_dir();
    if !token_dir.is_dir() {
        println!(
            "garminconnect: skipped, no token in {}. Run `runsync login` once to enable it.",
            token_dir.display()
        );
        return Ok(());
    }
    let interval = Duration::from_secs_f64(config.sync.garminconnect_interval_s.max(0.0));
    let mut source = GarminConnectScript::new(token_dir, interval);
    let options = MetricsSyncOptions {
        today: chrono::Local::now().date_naive(),
    };
    let report = sync_garmin_metrics(data_dir, &mut source, &options)?;
    drop(source);
    println!(
        "garminconnect: {} metric responses, {} could not be parsed",
        report.fetched, report.unparsable
    );
    match report.stopped_by {
        None => Ok(()),
        Some(SourceError::RateLimited(reason)) => bail!(
            "garminconnect rate limited ({reason}); stopped without retrying. \
             Run `runsync sync` again later; it resumes where it stopped."
        ),
        Some(SourceError::CredentialsRejected) => bail!(
            "the garminconnect token is missing, expired or was rejected. \
             Run `runsync login` to log in again."
        ),
        Some(SourceError::Other(err)) => Err(err.context(
            "garminconnect sync stopped; run `runsync sync` again to resume where it stopped",
        )),
    }
}

fn sync_personal_api(data_dir: &DataDir, config: &Config) -> Result<()> {
    let key_path = data_dir.personal_api_key_path();
    let key = ApiKey::load(&key_path)?;
    let interval = Duration::from_secs_f64(config.sync.personal_api_interval_s.max(0.0));
    let mut client = PersonalApiClient::new(key, interval)?;
    let report = sync_activities(data_dir, &mut client, &SyncOptions::default())?;
    println!(
        "personal_api: {} new activities, {} refreshed, {} FIT files, {} files could not be parsed",
        report.new_activities, report.refreshed_activities, report.fit_files, report.unparsable
    );
    match report.stopped_by {
        None => Ok(()),
        Some(SourceError::RateLimited(reason)) => bail!(
            "Personal API rate limited ({reason}); stopped without retrying. \
             Run `runsync sync` again later; it resumes where it stopped."
        ),
        Some(SourceError::CredentialsRejected) => bail!(
            "Personal API key was rejected. Generate a new key at \
             https://connect.garmin.com/app/settings/personalApiToken and save it to {}.",
            key_path.display()
        ),
        Some(SourceError::Other(err)) => Err(err.context(
            "Personal API sync stopped; run `runsync sync` again to resume where it stopped",
        )),
    }
}
