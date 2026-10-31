-- Hourly air temperature from the Open-Meteo historical weather archive
-- (raw/open-meteo/, `runsync sync` and `rebuild`). One row per requested
-- grid point and whole hour. grid_lat/grid_lon are the 0.1° grid point the
-- request asked for (the response's own coordinates are a model grid point
-- and are not stored); time_utc is ISO 8601 with a trailing Z, the start of
-- the hour; temperature_c is temperature_2m in °C, NULL where the archive
-- has no value.
--
-- sync_runs.source (migration 2) also takes 'open_meteo' from this version on.
CREATE TABLE hourly_weather (
    grid_lat      REAL NOT NULL,
    grid_lon      REAL NOT NULL,
    time_utc      TEXT NOT NULL,
    temperature_c REAL,
    PRIMARY KEY (grid_lat, grid_lon, time_utc)
) WITHOUT ROWID;
