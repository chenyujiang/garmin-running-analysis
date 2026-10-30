//! The garminconnect data source: the PEP 723 script
//! `importer/garminconnect/garmin_metrics.py`, run with `uv run --script`.
//!
//! - `runsync login` runs `garmin_metrics.py login` with the terminal attached:
//!   the script asks for email, password (getpass) and MFA code and stores
//!   only the token in `secrets/garminconnect/`.
//! - The metrics sync starts one `garmin_metrics.py serve` process per run,
//!   writes `<metric> <YYYY-MM-DD>` lines to its stdin and reads one JSON line
//!   per request from its stdout. The script paces the requests and exits on
//!   the first error; its exit code says what went wrong (see [`exit_error`]).
//!   The script never logs in with credentials, it only reuses the token.

use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Command, ExitStatus, Stdio};
use std::time::Duration;

use anyhow::{Context, anyhow, bail};
use chrono::NaiveDate;

use crate::source::{GarminMetric, MetricsSource, SourceError};

/// The script, located from the importer's source tree.
pub fn script_path() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("garminconnect")
        .join("garmin_metrics.py")
}

fn uv_script(args: &[&std::ffi::OsStr]) -> Command {
    let mut cmd = Command::new("uv");
    cmd.args(["run", "--quiet", "--script"]).arg(script_path());
    cmd.args(args);
    cmd
}

/// `runsync login`: interactive, the script talks to the terminal directly.
pub fn login(token_dir: &Path) -> anyhow::Result<()> {
    let status = uv_script(&[
        "login".as_ref(),
        "--token-dir".as_ref(),
        token_dir.as_os_str(),
    ])
    .status()
    .context("running `uv` (is uv installed and on PATH?)")?;
    match exit_error(status) {
        None => Ok(()),
        Some(SourceError::RateLimited(_)) => bail!(
            "Garmin refused the login (rate limited or CAPTCHA required). \
             Wait a while before trying `runsync login` again."
        ),
        Some(SourceError::CredentialsRejected) => {
            bail!("Garmin rejected the email, password or MFA code")
        }
        Some(SourceError::Other(err)) => Err(err.context("garminconnect login failed")),
    }
}

/// The script's exit code as a [`SourceError`]; `None` on success.
fn exit_error(status: ExitStatus) -> Option<SourceError> {
    match status.code() {
        Some(0) => None,
        Some(3) => Some(SourceError::CredentialsRejected),
        Some(4) => Some(SourceError::RateLimited(
            "garminconnect: HTTP 429 or CAPTCHA required".to_owned(),
        )),
        _ => Some(SourceError::Other(anyhow!(
            "garminconnect script failed ({status}); see its message above"
        ))),
    }
}

struct Running {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
}

/// The real [`MetricsSource`]: a lazily started `serve` process.
pub struct GarminConnectScript {
    token_dir: PathBuf,
    interval: Duration,
    running: Option<Running>,
}

impl GarminConnectScript {
    pub fn new(token_dir: PathBuf, interval: Duration) -> Self {
        Self {
            token_dir,
            interval,
            running: None,
        }
    }

    fn start(&mut self) -> Result<&mut Running, SourceError> {
        if self.running.is_none() {
            let interval = self.interval.as_secs_f64().to_string();
            let mut child = uv_script(&[
                "serve".as_ref(),
                "--token-dir".as_ref(),
                self.token_dir.as_os_str(),
                "--interval".as_ref(),
                interval.as_ref(),
            ])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .context("running `uv` (is uv installed and on PATH?)")?;
            let stdin = child.stdin.take().expect("piped");
            let stdout = BufReader::new(child.stdout.take().expect("piped"));
            self.running = Some(Running {
                child,
                stdin,
                stdout,
            });
        }
        Ok(self.running.as_mut().expect("just started"))
    }

    /// The process ended early: wait for it and turn its exit code into
    /// the error.
    fn failed(&mut self) -> SourceError {
        let Some(mut running) = self.running.take() else {
            return SourceError::Other(anyhow!("garminconnect script is not running"));
        };
        drop(running.stdin);
        match running.child.wait() {
            Ok(status) => exit_error(status).unwrap_or_else(|| {
                SourceError::Other(anyhow!("garminconnect script stopped answering"))
            }),
            Err(err) => SourceError::Other(anyhow!(err).context("waiting for the script")),
        }
    }
}

impl MetricsSource for GarminConnectScript {
    fn metric(&mut self, metric: GarminMetric, date: NaiveDate) -> Result<String, SourceError> {
        let running = self.start()?;
        let request = format!("{} {}\n", metric.key(), date.format("%Y-%m-%d"));
        if running.stdin.write_all(request.as_bytes()).is_err() || running.stdin.flush().is_err() {
            return Err(self.failed());
        }
        let mut line = String::new();
        match running.stdout.read_line(&mut line) {
            Ok(n) if n > 0 => Ok(line.trim_end().to_owned()),
            _ => Err(self.failed()),
        }
    }
}

impl Drop for GarminConnectScript {
    /// Close stdin so the script saves its refreshed token and exits.
    fn drop(&mut self) {
        if let Some(running) = self.running.take() {
            drop(running.stdin);
            let mut child = running.child;
            if let Err(err) = child.wait() {
                log::warn!("garminconnect script: {err}");
            }
        }
    }
}
