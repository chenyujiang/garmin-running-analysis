-- One row per day with Garmin's own metrics, picked from the garminconnect
-- responses in raw/garminconnect/<metric>/<YYYY-MM-DD>.json. Used only to
-- compare with our own numbers. Each metric fills its own columns, so a day
-- can have some metrics and not others; missing values are NULL.
-- Backfill stores one day per week (Sundays); later syncs add a snapshot
-- of the sync day.
CREATE TABLE garmin_metrics (
    date                  TEXT PRIMARY KEY,  -- YYYY-MM-DD, the day asked for
    -- training_status: the primary training device's status
    training_status       TEXT,              -- e.g. 'PRODUCTIVE_1' (trainingStatusFeedbackPhrase)
    acute_load            REAL,              -- dailyTrainingLoadAcute (Garmin's EPOC-based load)
    chronic_load          REAL,              -- dailyTrainingLoadChronic
    acute_chronic_ratio   REAL,              -- dailyAcuteChronicWorkloadRatio
    -- vo2max: running VO2max (ml/kg/min)
    vo2max                REAL,              -- vo2MaxPreciseValue
    -- race_predictor: predicted finish times in s
    race_5k_s             REAL,
    race_10k_s            REAL,
    race_half_marathon_s  REAL,
    race_marathon_s       REAL
) WITHOUT ROWID;
