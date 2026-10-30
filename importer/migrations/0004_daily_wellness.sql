-- One row per calendar day from the Personal API daily summaries
-- (`raw/personal_api/daily_summaries/<YYYY-MM-DD>.json`). Upserted: the last
-- 7 days are refetched on every sync. Days without data have no row; a row
-- may still hold NULLs (e.g. no resting heart rate that day). HRV and sleep
-- have no table: those responses are empty (the watch is not worn at night).
CREATE TABLE daily_wellness (
    calendar_date          TEXT PRIMARY KEY,  -- YYYY-MM-DD, the user's local day
    resting_hr_bpm         INTEGER,           -- heartRate.restingValue
    min_hr_bpm             INTEGER,           -- heartRate.minValue
    max_hr_bpm             INTEGER,           -- heartRate.maxValue
    steps                  INTEGER,           -- movement.steps.value
    steps_distance_m       REAL,              -- movement.steps.distanceInMeters
    calories_total_kcal    INTEGER,           -- calories.burnedTotal
    calories_active_kcal   INTEGER,           -- calories.burnedActive
    calories_resting_kcal  INTEGER,           -- calories.burnedResting
    intensity_moderate_min INTEGER,           -- intensityMinutes.moderate
    intensity_vigorous_min INTEGER,           -- intensityMinutes.vigorous
    stress_avg             INTEGER,           -- stress.avgLevel (0-100)
    body_battery_min       INTEGER,           -- bodyBattery.minValue
    body_battery_max       INTEGER,           -- bodyBattery.maxValue
    respiration_avg_brpm   REAL               -- respiration.avgValue, breaths/min
) WITHOUT ROWID;
