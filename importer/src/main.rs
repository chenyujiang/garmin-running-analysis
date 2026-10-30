use anyhow::Result;
use clap::{Parser, Subcommand};

use runsync::data_dir::DataDir;

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
    let _config = data_dir.load_config()?;
    match cli.command {
        Command::Sync => not_yet("sync"),
        Command::Login => not_yet("login"),
        Command::Rebuild => {
            let report = runsync::rebuild::rebuild(&data_dir)?;
            println!(
                "rebuilt {}: {} activities, {} files skipped",
                data_dir.analysis_db_path().display(),
                report.activities,
                report.skipped
            );
            Ok(())
        }
    }
}

fn not_yet(command: &str) -> Result<()> {
    println!("runsync {command}: 尚未实现 (not implemented yet)");
    Ok(())
}
