use std::path::PathBuf;
use std::time::Duration;

use anyhow::{Result, bail};
use clap::{Parser, Subcommand};

use runsync::config::Config;
use runsync::data_dir::DataDir;
use runsync::garminconnect::GarminConnectScript;
use runsync::personal_api::{ApiKey, PersonalApiClient};
use runsync::source::{ActivitySource, MetricsSource};
use runsync::sync::SyncOptions;
use runsync::sync_all::{Outcome, sync_all};
use runsync::weather::OpenMeteoClient;

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
    /// Fetch new and recently changed data from Garmin. Never asks for a password.
    Sync,
    /// Log in to garminconnect interactively and store its token under secrets/.
    Login,
    /// Delete the analysis database and recreate it from the raw archive (offline).
    Rebuild,
    /// Archive a Garmin account export (.zip) under raw/export/ and load its history (offline).
    ImportExport {
        /// The export package as downloaded from Garmin.
        zip: PathBuf,
    },
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
                "rebuilt {}: {} activities, {} FIT files, {} daily summaries, {} Garmin metric files, {} export packages, {} hours of air temperature, {} files skipped",
                data_dir.analysis_db_path().display(),
                report.activities,
                report.fit_files,
                report.daily_summaries,
                report.garmin_metrics,
                report.export_packages,
                report.weather_hours,
                report.skipped
            );
            Ok(())
        }
        Command::ImportExport { zip } => {
            for report in runsync::export::import_export(&data_dir, &zip)? {
                print!("{report}");
            }
            Ok(())
        }
    }
}

/// All three sources run on every sync, one after the other; one failing does
/// not stop the others. Building the sources touches neither the network nor the
/// script, so a source in cooldown makes no request at all.
fn sync(data_dir: &DataDir, config: &Config) -> Result<()> {
    let personal_interval = Duration::from_secs_f64(config.sync.personal_api_interval_s.max(0.0));
    let mut personal = ApiKey::load(&data_dir.personal_api_key_path())
        .and_then(|key| PersonalApiClient::new(key, personal_interval));

    let token_dir = data_dir.garminconnect_token_dir();
    let mut garminconnect = token_dir.is_dir().then(|| {
        let interval = Duration::from_secs_f64(config.sync.garminconnect_interval_s.max(0.0));
        GarminConnectScript::new(token_dir, interval)
    });
    let mut open_meteo = OpenMeteoClient::new()?;

    let report = sync_all(
        data_dir,
        &SyncOptions::default(),
        personal
            .as_mut()
            .map(|c| c as &mut dyn ActivitySource)
            .map_err(|err| anyhow::anyhow!("{err:#}")),
        garminconnect.as_mut().map(|s| s as &mut dyn MetricsSource),
        &mut open_meteo,
    );
    // Close the script so it saves its refreshed token.
    drop(garminconnect);

    for outcome in [
        &report.personal_api,
        &report.garminconnect,
        &report.open_meteo,
    ] {
        match outcome {
            Outcome::Done(m) | Outcome::Skipped(m) => println!("{m}"),
            Outcome::Failed(m) => eprintln!("error: {m}"),
        }
    }
    if !report.success() {
        bail!("sync did not complete (see above)");
    }
    Ok(())
}
