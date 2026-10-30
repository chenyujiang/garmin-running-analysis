-- Per-second data stream and watch laps, parsed from the activity FIT file
-- (raw/personal_api/activities/<activityId>.fit). Private manufacturer
-- messages (`unknown_*`) are not stored. Missing values are NULL.
--
-- records units: timestamp ISO 8601 UTC with Z; heart_rate bpm; speed m/s;
-- cadence single-foot steps/min as in the FIT file (double it for spm);
-- altitude m; distance m (cumulative); lat/lon degrees; power W;
-- temperature °C (watch sensor).
CREATE TABLE records (
    activity_id INTEGER NOT NULL,
    timestamp   TEXT    NOT NULL,
    heart_rate  REAL,
    speed       REAL,
    cadence     REAL,
    altitude    REAL,
    distance    REAL,
    lat         REAL,
    lon         REAL,
    power       REAL,
    temperature REAL,
    PRIMARY KEY (activity_id, timestamp)
) WITHOUT ROWID;

-- One row per lap message, numbered from 0 in file order.
-- avg_cadence and max_cadence are single-foot steps/min as in the FIT file.
CREATE TABLE laps (
    activity_id        INTEGER NOT NULL,
    lap_index          INTEGER NOT NULL,
    start_time_utc     TEXT,
    end_time_utc       TEXT,
    elapsed_duration_s REAL,
    timer_duration_s   REAL,
    distance_m         REAL,
    avg_speed_mps      REAL,
    max_speed_mps      REAL,
    avg_hr_bpm         REAL,
    max_hr_bpm         REAL,
    avg_cadence        REAL,
    max_cadence        REAL,
    avg_power_w        REAL,
    elevation_gain_m   REAL,
    elevation_loss_m   REAL,
    PRIMARY KEY (activity_id, lap_index)
);
