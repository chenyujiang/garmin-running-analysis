//! An in-memory `ActivitySource` for Seam 2 tests: no HTTP, no delays.
//! It records which pages and files were requested so tests can check what
//! `sync` asked the data source for.

use std::collections::BTreeMap;

use chrono::{DateTime, NaiveDate, Utc};
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
    pub fn error(&self) -> SourceError {
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
    /// Daily summary rows by calendar date; days not in here have no data.
    daily: BTreeMap<NaiveDate, serde_json::Value>,
    pub list_requests: Vec<(usize, usize)>,
    pub detail_requests: Vec<i64>,
    pub fit_requests: Vec<i64>,
    /// `(start, end)` of every daily summary request, inclusive.
    pub daily_requests: Vec<(NaiveDate, NaiveDate)>,
    /// Fail when asked for this activity's detail JSON.
    pub fail_detail: Option<(i64, Failure)>,
    /// Fail on the daily summary request whose range holds this date.
    pub fail_daily: Option<(NaiveDate, Failure)>,
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

    /// Serve a daily summary for `day` with this resting heart rate.
    pub fn with_daily(mut self, day: NaiveDate, resting_hr: Option<i64>) -> Self {
        self.daily.insert(day, daily_summary_row(day, resting_hr));
        self
    }

    pub fn failing_daily(mut self, day: NaiveDate, failure: Failure) -> Self {
        self.fail_daily = Some((day, failure));
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

    fn daily_summaries(&mut self, start: NaiveDate, end: NaiveDate) -> Result<String, SourceError> {
        self.daily_requests.push((start, end));
        if let Some((day, failure)) = &self.fail_daily
            && (start..=end).contains(day)
        {
            return Err(failure.error());
        }
        let rows: Vec<_> = self.daily.range(start..=end).map(|(_, v)| v).collect();
        Ok(serde_json::json!({ "data": rows }).to_string())
    }
}

/// A daily summary row shaped like the Personal API's
/// `/usersummary-service/v2/dailysummaries` (trimmed).
pub fn daily_summary_row(day: NaiveDate, resting_hr: Option<i64>) -> serde_json::Value {
    serde_json::json!({
        "calendarDate": day.format("%Y-%m-%d").to_string(),
        "source": "garmin",
        "includesWellnessData": true,
        "movement": { "steps": { "goal": 8000, "value": 9012, "distanceInMeters": 7210.5 } },
        "calories": { "burnedResting": 1650, "burnedActive": 540, "burnedTotal": 2190 },
        "heartRate": { "minValue": 48, "maxValue": 171, "restingValue": resting_hr },
        "intensityMinutes": { "goal": 150, "moderate": 12, "vigorous": 31 },
        "stress": { "avgLevel": 27 },
        "bodyBattery": { "minValue": 21, "maxValue": 88 },
        "respiration": { "avgValue": 14 }
    })
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
