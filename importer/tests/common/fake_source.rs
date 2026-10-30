//! An in-memory `ActivitySource` for Seam 2 tests: no HTTP, no delays.
//! It records which pages and files were requested so tests can check what
//! `sync` asked the data source for.

use chrono::{DateTime, Utc};
use runsync::source::{ActivitySource, ListedActivity, SourceError};

use super::fit::{FitWriter, MESG_RECORD, UINT8, UINT32, field, fit_time};

#[derive(Clone)]
pub struct FakeActivity {
    pub activity_id: i64,
    pub start_time_utc: DateTime<Utc>,
    pub detail_json: String,
    pub fit: Option<Vec<u8>>,
}

impl FakeActivity {
    /// A running activity with a detail JSON named `name` and a tiny FIT
    /// file holding two records.
    pub fn run(activity_id: i64, start_time_utc: DateTime<Utc>, name: &str) -> Self {
        Self {
            activity_id,
            start_time_utc,
            detail_json: detail_json(activity_id, start_time_utc, name),
            fit: Some(tiny_fit(start_time_utc)),
        }
    }

    pub fn without_fit(mut self) -> Self {
        self.fit = None;
        self
    }
}

/// What the fake does when asked for a given activity's file.
#[derive(Clone)]
pub enum Failure {
    RateLimited,
    CredentialsRejected,
    Other,
}

impl Failure {
    fn error(&self) -> SourceError {
        match self {
            Failure::RateLimited => SourceError::RateLimited("HTTP 429".into()),
            Failure::CredentialsRejected => SourceError::CredentialsRejected,
            Failure::Other => SourceError::Other(anyhow::anyhow!("HTTP 500")),
        }
    }
}

#[derive(Default)]
pub struct FakeSource {
    /// Newest first, the order the activity list returns them in.
    activities: Vec<FakeActivity>,
    pub list_requests: Vec<(usize, usize)>,
    pub detail_requests: Vec<i64>,
    pub fit_requests: Vec<i64>,
    /// Fail when asked for this activity's detail JSON.
    pub fail_detail: Option<(i64, Failure)>,
}

impl FakeSource {
    pub fn new(mut activities: Vec<FakeActivity>) -> Self {
        activities.sort_by_key(|a| std::cmp::Reverse(a.start_time_utc));
        Self {
            activities,
            ..Self::default()
        }
    }

    pub fn failing_detail(mut self, activity_id: i64, failure: Failure) -> Self {
        self.fail_detail = Some((activity_id, failure));
        self
    }

    fn find(&self, activity_id: i64) -> Result<&FakeActivity, SourceError> {
        self.activities
            .iter()
            .find(|a| a.activity_id == activity_id)
            .ok_or_else(|| SourceError::Other(anyhow::anyhow!("no activity {activity_id}")))
    }
}

impl ActivitySource for FakeSource {
    fn list_activities(
        &mut self,
        start: usize,
        limit: usize,
    ) -> Result<Vec<ListedActivity>, SourceError> {
        self.list_requests.push((start, limit));
        Ok(self
            .activities
            .iter()
            .skip(start)
            .take(limit)
            .map(|a| ListedActivity {
                activity_id: a.activity_id,
                start_time_utc: a.start_time_utc,
            })
            .collect())
    }

    fn activity_detail(&mut self, activity_id: i64) -> Result<String, SourceError> {
        self.detail_requests.push(activity_id);
        if let Some((id, failure)) = &self.fail_detail
            && *id == activity_id
        {
            return Err(failure.error());
        }
        Ok(self.find(activity_id)?.detail_json.clone())
    }

    fn activity_fit(&mut self, activity_id: i64) -> Result<Option<Vec<u8>>, SourceError> {
        self.fit_requests.push(activity_id);
        Ok(self.find(activity_id)?.fit.clone())
    }
}

/// A minimal Personal API activity detail JSON.
pub fn detail_json(activity_id: i64, start_time_utc: DateTime<Utc>, name: &str) -> String {
    let gmt = start_time_utc.format("%Y-%m-%dT%H:%M:%S.0");
    serde_json::json!({
        "activityId": activity_id,
        "activityName": name,
        "activityTypeDTO": { "typeKey": "running" },
        "timeZoneUnitDTO": { "timeZone": "UTC" },
        "summaryDTO": {
            "startTimeLocal": gmt.to_string(),
            "startTimeGMT": gmt.to_string(),
            "distance": 5000.0,
            "duration": 1500.0
        }
    })
    .to_string()
}

/// A FIT file with two one-second records starting at `start`.
pub fn tiny_fit(start: DateTime<Utc>) -> Vec<u8> {
    let t = start.timestamp();
    FitWriter::new()
        .message(
            MESG_RECORD,
            &[field(253, UINT32, fit_time(t)), field(3, UINT8, 140)],
        )
        .message(
            MESG_RECORD,
            &[field(253, UINT32, fit_time(t + 1)), field(3, UINT8, 142)],
        )
        .finish()
}
