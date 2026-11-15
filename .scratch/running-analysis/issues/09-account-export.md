# Request a Garmin account data export

Type: task
Status: open
Blocked by: none

## Question

Request one full account data export in the Garmin account settings (Garmin takes a few days to prepare it). The raw FIT files in the export are byte-for-byte the files on the watch, so they can serve as a fallback raw archive of the 5-year history. The export also shows the format of the health data (HRV, sleep, resting heart rate), which the [Garmin Connect data access survey](01-garmin-data-access.md) could not confirm.

The user must do this in person (HITL). Once the export arrives, record in the Answer: where the archive is kept, its directory layout, the number of FIT files and their date range, and the file format of the health data.

## Comments

- 2026-10-23 (from [project skeleton and dependencies](11-project-skeleton.md)): the environment variable `RUNNING_DATA_DIR` sets the data directory, default `%USERPROFILE%\running-data`. The export is extracted to `raw/export/<export date>/` in it.
- 2026-10-24: this blocks no ticket and does not block closing the map. The user requests the export on the Garmin website; once it arrives, record the Answer and close this ticket.
