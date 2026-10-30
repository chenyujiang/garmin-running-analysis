//! The data source seam. `sync` only talks to an [`ActivitySource`]; the real
//! implementation is the Personal API client in [`crate::personal_api`],
//! tests use an in-memory fake.

use chrono::{DateTime, NaiveDate, Utc};

/// One entry of the activity list, newest first.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ListedActivity {
    pub activity_id: i64,
    pub start_time_utc: DateTime<Utc>,
}

/// Why a data source call failed. `sync` stops the source on any of these.
#[derive(Debug, thiserror::Error)]
pub enum SourceError {
    /// HTTP 429 or `CAPTCHA_REQUIRED`. Never retried.
    #[error("rate limited: {0}")]
    RateLimited(String),
    /// The key or token was rejected (HTTP 401/403).
    #[error("credentials rejected")]
    CredentialsRejected,
    #[error(transparent)]
    Other(#[from] anyhow::Error),
}

impl SourceError {
    /// The `sync_runs.outcome` value for a run stopped by this error.
    pub fn outcome(&self) -> &'static str {
        match self {
            SourceError::RateLimited(_) => "rate_limited",
            SourceError::CredentialsRejected => "auth_failed",
            SourceError::Other(_) => "error",
        }
    }
}

pub trait ActivitySource {
    /// Up to `limit` activities of all types, newest first, skipping the
    /// newest `start`.
    fn list_activities(
        &mut self,
        start: usize,
        limit: usize,
    ) -> Result<Vec<ListedActivity>, SourceError>;

    /// The activity detail JSON, exactly as served.
    fn activity_detail(&mut self, activity_id: i64) -> Result<String, SourceError>;

    /// The activity's FIT file, or `None` when it has none (e.g. a manually
    /// entered activity).
    fn activity_fit(&mut self, activity_id: i64) -> Result<Option<Vec<u8>>, SourceError>;

    /// Daily summaries for the inclusive date range, exactly as served: a
    /// JSON object whose `data` array holds one row per day that has data.
    fn daily_summaries(&mut self, start: NaiveDate, end: NaiveDate) -> Result<String, SourceError>;
}
