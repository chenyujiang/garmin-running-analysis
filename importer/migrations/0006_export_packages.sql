-- One row per Garmin account export package loaded from
-- raw/export/<YYYY-MM-DD>/<file>.zip (`runsync import-export`, `rebuild`).
-- The export holds the account's whole history up to its export date, so a
-- day from the first row of a kind up to export_date is covered by it even
-- without a row: sync does not backfill such days from the APIs.
CREATE TABLE export_packages (
    package        TEXT PRIMARY KEY,  -- '<YYYY-MM-DD>/<file name>' under raw/export
    export_date    TEXT NOT NULL,     -- YYYY-MM-DD, newest entry modification date
    daily_first    TEXT,              -- first UDS calendarDate (daily summaries), NULL if none
    metrics_first  TEXT               -- first VO2max/race predictor/training status date, NULL if none
) WITHOUT ROWID;
