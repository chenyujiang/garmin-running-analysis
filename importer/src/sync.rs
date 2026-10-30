//! `runsync sync` for activities: pull new activities (all types) from an
//! [`ActivitySource`] into the raw archive and the analysis database.
//!
//! - The activity list is paged newest first until a page whose activities
//!   are all already in the raw archive.
//! - Activities from the last 7 days get their detail JSON refetched and
//!   overwritten; a FIT is only downloaded when missing.
//! - Resuming relies only on which raw files exist; no progress is stored.
//!   For each activity the FIT is fetched before the detail JSON, so an
//!   existing `<id>.json` means that activity is complete.
//! - Daily summaries: the last 7 days (up to `today`) are refetched and
//!   overwritten on every run; older days are fetched back to 2021-08-01 in
//!   7-day ranges, newest first, skipping ranges whose day files all exist.
//!   A day without data is archived as `null`, so it is not asked for again.
//! - Every file is written atomically and loaded into the database at once,
//!   so an interrupted run leaves usable partial results.

use std::path::Path;

use anyhow::{Context, Result};
use chrono::{DateTime, Duration, Local, NaiveDate, SecondsFormat, Utc};
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::{Connection, params};

use crate::activity::Activity;
use crate::daily;
use crate::data_dir::DataDir;
use crate::db;
use crate::fit::ActivityFit;
use crate::source::{ActivitySource, SourceError};

pub const SOURCE_NAME: &str = "personal_api";
pub const DEFAULT_PAGE_SIZE: usize = 100;
/// Activities that started within this window are refetched on every sync.
pub const REFRESH_WINDOW_DAYS: i64 = 7;
/// Daily summaries are requested this many days at a time.
pub const DAILY_RANGE_DAYS: i64 = 7;
/// First day of the daily summaries backfill.
pub const DAILY_BACKFILL_START: NaiveDate = NaiveDate::from_ymd_opt(2021, 8, 1).unwrap();

#[derive(Debug, Clone)]
pub struct SyncOptions {
    pub now: DateTime<Utc>,
    /// The runner's local calendar date: the last day of daily summaries.
    pub today: NaiveDate,
    pub page_size: usize,
}

impl Default for SyncOptions {
    fn default() -> Self {
        let now = Utc::now();
        Self {
            now,
            today: now.with_timezone(&Local).date_naive(),
            page_size: DEFAULT_PAGE_SIZE,
        }
    }
}

#[derive(Debug, Default)]
pub struct SyncReport {
    /// Detail JSON files downloaded for activities not yet in the archive.
    pub new_activities: usize,
    /// Detail JSON files refetched and overwritten (last 7 days).
    pub refreshed_activities: usize,
    pub fit_files: usize,
    /// Daily summary day files written (new or overwritten).
    pub daily_summaries: usize,
    /// Downloaded files kept in the raw archive that could not be parsed.
    pub unparsable: usize,
    /// Set when the run stopped early; everything before it is kept.
    pub stopped_by: Option<SourceError>,
}

/// Sync activities from `source`. Source failures stop the run and are
/// returned in [`SyncReport::stopped_by`]; the run is recorded in
/// `sync_runs` either way.
pub fn sync_activities(
    data_dir: &DataDir,
    source: &mut dyn ActivitySource,
    options: &SyncOptions,
) -> Result<SyncReport> {
    let started_at = utc_now_string();
    let conn = db::open(&data_dir.analysis_db_path())?;
    let dir = data_dir.personal_api_activities_dir();
    std::fs::create_dir_all(&dir).with_context(|| format!("creating {}", dir.display()))?;

    let progress = ProgressBar::new_spinner();
    progress.set_style(
        ProgressStyle::with_template("{spinner} {elapsed_precise} {pos} files  {msg}")
            .expect("valid template"),
    );

    let mut run = Run {
        conn: &conn,
        dir: &dir,
        source,
        progress: &progress,
        report: SyncReport::default(),
    };
    let daily_dir = data_dir.personal_api_daily_summaries_dir();
    std::fs::create_dir_all(&daily_dir)
        .with_context(|| format!("creating {}", daily_dir.display()))?;
    let result = run
        .pages(options)
        .and_then(|()| run.daily_summaries(&daily_dir, options.today));
    if let Err(err) = result {
        log::warn!("personal_api sync stopped: {err}");
        run.report.stopped_by = Some(err);
    }
    progress.finish_and_clear();
    let report = run.report;

    let outcome = report
        .stopped_by
        .as_ref()
        .map_or("ok", SourceError::outcome);
    conn.execute(
        "INSERT INTO sync_runs (source, started_at_utc, finished_at_utc, outcome)
         VALUES (?1, ?2, ?3, ?4)",
        params![SOURCE_NAME, started_at, utc_now_string(), outcome],
    )?;
    Ok(report)
}

struct Run<'a> {
    conn: &'a Connection,
    dir: &'a Path,
    source: &'a mut dyn ActivitySource,
    progress: &'a ProgressBar,
    report: SyncReport,
}

impl Run<'_> {
    fn pages(&mut self, options: &SyncOptions) -> Result<(), SourceError> {
        let refresh_after = options.now - Duration::days(REFRESH_WINDOW_DAYS);
        let mut start = 0;
        loop {
            let page = self.source.list_activities(start, options.page_size)?;
            let Some(oldest) = page.last() else { break };
            let oldest_is_recent = oldest.start_time_utc >= refresh_after;
            let mut all_present = true;
            for listed in &page {
                let present = self.json_path(listed.activity_id).is_file();
                all_present &= present;
                let recent = listed.start_time_utc >= refresh_after;
                if present && !recent {
                    continue;
                }
                self.activity(listed.activity_id, present)?;
            }
            // Keep paging past a fully archived page only while it may still
            // hold activities in the refresh window.
            if (all_present && !oldest_is_recent) || page.len() < options.page_size {
                break;
            }
            start += page.len();
        }
        Ok(())
    }

    fn activity(&mut self, activity_id: i64, refresh: bool) -> Result<(), SourceError> {
        self.progress.set_message(format!("activity {activity_id}"));
        let fit_path = self.dir.join(format!("{activity_id}.fit"));
        if !fit_path.is_file()
            && let Some(bytes) = self.source.activity_fit(activity_id)?
        {
            write_atomically(&fit_path, &bytes)?;
            self.report.fit_files += 1;
            self.progress.inc(1);
            if let Err(err) = self.load_fit(activity_id, &bytes) {
                log::warn!("could not parse {}: {err:#}", fit_path.display());
                self.report.unparsable += 1;
            }
        }

        let detail = self.source.activity_detail(activity_id)?;
        let json_path = self.json_path(activity_id);
        write_atomically(&json_path, detail.as_bytes())?;
        if refresh {
            self.report.refreshed_activities += 1;
        } else {
            self.report.new_activities += 1;
        }
        self.progress.inc(1);
        let loaded = Activity::from_detail_json(&detail).and_then(|a| a.upsert(self.conn));
        if let Err(err) = loaded {
            log::warn!("could not load {}: {err:#}", json_path.display());
            self.report.unparsable += 1;
        }
        Ok(())
    }

    fn load_fit(&self, activity_id: i64, bytes: &[u8]) -> Result<()> {
        let fit = ActivityFit::parse(bytes)?;
        let tx = self.conn.unchecked_transaction()?;
        fit.store(&tx, activity_id)?;
        tx.commit()?;
        Ok(())
    }

    /// Refetch the last 7 days, then backfill older ranges, newest first.
    fn daily_summaries(&mut self, dir: &Path, today: NaiveDate) -> Result<(), SourceError> {
        let mut end = today;
        let mut refresh = true;
        while end >= DAILY_BACKFILL_START {
            let start = (end - Duration::days(DAILY_RANGE_DAYS - 1)).max(DAILY_BACKFILL_START);
            let archived = start
                .iter_days()
                .take_while(|d| *d <= end)
                .all(|d| daily_path(dir, d).is_file());
            if refresh || !archived {
                self.daily_range(dir, start, end)?;
            }
            refresh = false;
            end = start - Duration::days(1);
        }
        Ok(())
    }

    fn daily_range(
        &mut self,
        dir: &Path,
        start: NaiveDate,
        end: NaiveDate,
    ) -> Result<(), SourceError> {
        self.progress
            .set_message(format!("daily summaries {start}..{end}"));
        let body = self.source.daily_summaries(start, end)?;
        let days = daily::split_response(&body, start, end)
            .with_context(|| format!("daily summaries {start}..{end}"))?;
        for (day, text) in days {
            let path = daily_path(dir, day);
            write_atomically(&path, text.as_bytes())?;
            self.report.daily_summaries += 1;
            self.progress.inc(1);
            if let Err(err) = daily::store_day(self.conn, &text) {
                log::warn!("could not load {}: {err:#}", path.display());
                self.report.unparsable += 1;
            }
        }
        Ok(())
    }

    fn json_path(&self, activity_id: i64) -> std::path::PathBuf {
        self.dir.join(format!("{activity_id}.json"))
    }
}

fn daily_path(dir: &Path, day: NaiveDate) -> std::path::PathBuf {
    dir.join(format!("{}.json", day.format("%Y-%m-%d")))
}

/// Write via a `.part` file and rename, so a file in the archive is always
/// complete. An existing file is replaced.
fn write_atomically(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut part = path.as_os_str().to_owned();
    part.push(".part");
    std::fs::write(&part, bytes).with_context(|| format!("writing {}", path.display()))?;
    std::fs::rename(&part, path).with_context(|| format!("writing {}", path.display()))?;
    Ok(())
}

fn utc_now_string() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Secs, true)
}
