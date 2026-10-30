//! An in-memory `MetricsSource` for Seam 2 tests: no Python script, no
//! network, no delays. Responses are hand-written in the shape garminconnect
//! returns; it records every request so tests can check what sync asked for.

use chrono::NaiveDate;
use runsync::source::{GarminMetric, MetricsSource, SourceError};

use super::fake_source::Failure;

#[derive(Default)]
pub struct FakeMetrics {
    pub requests: Vec<(GarminMetric, NaiveDate)>,
    /// Fail when asked for this metric on this date.
    pub fail: Option<(GarminMetric, NaiveDate, Failure)>,
    /// Added to every value, so a refetch can be told apart from the
    /// original response.
    pub offset: f64,
}

impl FakeMetrics {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn failing(mut self, metric: GarminMetric, date: NaiveDate, failure: Failure) -> Self {
        self.fail = Some((metric, date, failure));
        self
    }

    pub fn with_offset(mut self, offset: f64) -> Self {
        self.offset = offset;
        self
    }

    pub fn requested_dates(&self, metric: GarminMetric) -> Vec<NaiveDate> {
        self.requests
            .iter()
            .filter(|(m, _)| *m == metric)
            .map(|(_, d)| *d)
            .collect()
    }
}

impl MetricsSource for FakeMetrics {
    fn metric(&mut self, metric: GarminMetric, date: NaiveDate) -> Result<String, SourceError> {
        self.requests.push((metric, date));
        if let Some((m, d, failure)) = &self.fail
            && *m == metric
            && *d == date
        {
            return Err(failure.error());
        }
        Ok(response(metric, date, self.offset))
    }
}

/// A response in garminconnect's shape for `metric` on `date`.
pub fn response(metric: GarminMetric, date: NaiveDate, offset: f64) -> String {
    let day = date.format("%Y-%m-%d").to_string();
    match metric {
        GarminMetric::TrainingStatus => training_status_json(&day, 480.0 + offset),
        GarminMetric::Vo2Max => vo2max_json(&day, 52.4 + offset),
        GarminMetric::RacePredictor => race_predictor_json(&day, 1260.0 + offset),
    }
}

/// `get_training_status(cdate)`: status per device, the primary one marked.
pub fn training_status_json(day: &str, acute: f64) -> String {
    serde_json::json!({
        "userId": 1,
        "mostRecentVO2Max": null,
        "mostRecentTrainingLoadBalance": null,
        "mostRecentTrainingStatus": {
            "userId": 1,
            "latestTrainingStatusData": {
                "111": {
                    "calendarDate": day,
                    "trainingStatus": 2,
                    "trainingStatusFeedbackPhrase": "MAINTAINING_1",
                    "primaryTrainingDevice": false,
                    "acuteTrainingLoadDTO": {
                        "dailyTrainingLoadAcute": 1.0,
                        "dailyTrainingLoadChronic": 1.0,
                        "dailyAcuteChronicWorkloadRatio": 1.0
                    }
                },
                "222": {
                    "calendarDate": day,
                    "trainingStatus": 7,
                    "trainingStatusFeedbackPhrase": "PRODUCTIVE_1",
                    "primaryTrainingDevice": true,
                    "acuteTrainingLoadDTO": {
                        "dailyTrainingLoadAcute": acute,
                        "dailyTrainingLoadChronic": 400.0,
                        "dailyAcuteChronicWorkloadRatio": 1.2
                    }
                }
            }
        }
    })
    .to_string()
}

/// `get_max_metrics(cdate)`: a list with one entry per day.
pub fn vo2max_json(day: &str, vo2max: f64) -> String {
    serde_json::json!([{
        "userId": 1,
        "generic": {
            "calendarDate": day,
            "vo2MaxPreciseValue": vo2max,
            "vo2MaxValue": vo2max.round()
        },
        "cycling": null
    }])
    .to_string()
}

/// `get_race_predictions(date, date, "daily")`: a list with one entry per day.
pub fn race_predictor_json(day: &str, time_5k: f64) -> String {
    serde_json::json!([{
        "userId": 1,
        "calendarDate": day,
        "time5K": time_5k,
        "time10K": 2640,
        "timeHalfMarathon": 5880,
        "timeMarathon": 12600
    }])
    .to_string()
}
