-- One row per activity, picked from the Personal API detail JSON
-- (raw/personal_api/activities/<activityId>.json). Units are SI:
-- m, s, m/s, bpm. start_time_utc is ISO 8601 with a trailing Z;
-- start_time_local is the wall-clock time where the activity happened,
-- without offset. The full JSON stays in the raw archive.
-- time_zone is an IANA name or a fixed offset: the Personal API gives the
-- IANA name; for account export activities it comes from start_time_local
-- minus start_time_utc, written 'Pacific/Auckland' when Auckland had that
-- offset at the time and otherwise as a fixed offset such as '+08:00'.
CREATE TABLE activities (
    activity_id        INTEGER PRIMARY KEY,
    activity_type      TEXT    NOT NULL,
    activity_name      TEXT,
    start_time_utc     TEXT    NOT NULL,
    start_time_local   TEXT    NOT NULL,
    time_zone          TEXT,
    distance_m         REAL,
    duration_s         REAL,
    moving_duration_s  REAL,
    elapsed_duration_s REAL,
    avg_speed_mps      REAL,
    max_speed_mps      REAL,
    avg_hr_bpm         REAL,
    max_hr_bpm         REAL,
    elevation_gain_m   REAL,
    elevation_loss_m   REAL,
    calories_kcal      REAL
);

CREATE INDEX activities_start_time_local ON activities (start_time_local);
