-- One row per finished `runsync sync` run and data source. The dashboard's
-- "last synced" time is max(finished_at_utc). `rebuild` starts from an empty
-- database, so this history does not survive a rebuild.
CREATE TABLE sync_runs (
    id              INTEGER PRIMARY KEY,
    source          TEXT NOT NULL,   -- 'personal_api' or 'garminconnect'
    started_at_utc  TEXT NOT NULL,   -- ISO 8601, trailing Z
    finished_at_utc TEXT NOT NULL,
    outcome         TEXT NOT NULL    -- 'ok', 'rate_limited', 'auth_failed', 'error', 'skipped'
);
