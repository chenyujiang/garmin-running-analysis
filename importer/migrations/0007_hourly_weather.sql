-- Hourly air temperature from the Open-Meteo historical weather archive
-- (raw/open-meteo/, `runsync sync` and `rebuild`). One row per requested
-- grid point and whole hour. grid_lat/grid_lon are the 0.1° grid point the
-- request asked for (the response's own coordinates are a model grid point
-- and are not stored); time_utc is ISO 8601 with a trailing Z, the start of
-- the hour; temperature_c is temperature_2m in °C, NULL where the archive
-- has no value.
--
-- sync_runs.source (migration 2) also takes 'open_meteo' from this version on.
--
-- Notes on earlier tables (shipped migrations are never edited, so they live
-- here):
-- * activities.time_zone (migration 1) is an IANA name or a fixed offset:
--   the Personal API gives the IANA name; for account export activities it
--   comes from start_time_local minus start_time_utc, written
--   'Pacific/Auckland' when Auckland had that offset at the time and
--   otherwise as a fixed offset such as '+08:00'.
-- * daily_wellness.resting_hr_bpm (migration 4) is always NULL: the watch is
--   worn in the daytime only, so Garmin's resting heart rate is too high to
--   use. The analysis takes the resting heart rate from hr_rest in
--   config.toml; the raw archive keeps Garmin's value.
CREATE TABLE hourly_weather (
    grid_lat      REAL NOT NULL,
    grid_lon      REAL NOT NULL,
    time_utc      TEXT NOT NULL,
    temperature_c REAL,
    PRIMARY KEY (grid_lat, grid_lon, time_utc)
) WITHOUT ROWID;
