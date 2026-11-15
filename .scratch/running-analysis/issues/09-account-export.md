# Request a Garmin account data export

Type: task
Status: resolved
Blocked by: none

## Question

Request one full account data export in the Garmin account settings (Garmin takes a few days to prepare it). The raw FIT files in the export are byte-for-byte the files on the watch, so they can serve as a fallback raw archive of the 5-year history. The export also shows the format of the health data (HRV, sleep, resting heart rate), which the [Garmin Connect data access survey](01-garmin-data-access.md) could not confirm.

The user must do this in person (HITL). Once the export arrives, record in the Answer: where the archive is kept, its directory layout, the number of FIT files and their date range, and the file format of the health data.

## Answer

Checked on 2026-11-15 from the directory listing and the zip entry names only (no file contents read), plus read-only aggregates from `running.sqlite`. File names that contain the account email are given here as `<email>`.

- **Where it is kept:** `raw/export/2026-10-30/` under `RUNNING_DATA_DIR`, as the single zip Garmin sent (about 110 MB, named `<uuid>_1.zip`), unchanged and not extracted. `runsync import-export` put it there and loaded it into `running.sqlite` (`export_packages`: export date 2026-10-30, daily summaries from 2021-08-06, Garmin metrics from 2021-08-07).
- **Directory layout inside the zip** (folder: files):
  - `DI_CONNECT/DI-Connect-Uploaded-Files/`: 3 nested zips, `UploadedFiles_0-_Part1.zip` to `Part3.zip`, holding only `.fit` files named `<email>_<upload id>.fit`.
  - `DI_CONNECT/DI-Connect-Fitness/`: 9 JSON, `<email>_<n>_summarizedActivities.json` (4 parts) plus gear, personal records, training plan, weekly training report and workouts.
  - `DI_CONNECT/DI-Connect-Aggregator/`: 20 `UDSFile_<from>_<to>.json` (daily summaries) and 20 `HydrationLogFile_<from>_<to>.json`.
  - `DI_CONNECT/DI-Connect-Wellness/`: 20 `<from>_<to>_<id>_sleepData.json`, plus `userBioMetrics`, `userBioMetricProfileData`, `bioMetrics_latest` and `heartRateZones` JSON.
  - `DI_CONNECT/DI-Connect-Metrics/`: 20 each of `MetricsMaxMetData_*.json` (VO2max), `RunRacePredictions_*.json` and `TrainingHistory_*.json` (training status).
  - `DI_CONNECT/DI-Connect-User/` (9 JSON, 3 JPEG: profile, goals, contact, reminders), `DI-Connect-Routing/` (2), `DI-Connect-Social/` (1), `DI-ATP/` (1), `DI-GOLF/` (2), and the top-level `DI_CONNECT_IQ/`, `DI_FACEIT_CLOUD/`, `DI_LIVETRACK/`, `IT_CONSENT_HISTORY/`, `IT_DEVICE_AND_CONTENT/`, `IT_GLOBAL_EVENT/`, `customer_data/` (one file each).
- **FIT files:** 17,770 (6,886 + 5,972 + 4,912 in the three parts). A rerun of `runsync import-export` on the archived zip (2026-11-15) sorted them: 1,094 activity FITs loaded, 3 activity FITs kept from the API, 16,673 not an activity (daily monitoring, settings and the like; skipped), 0 matching no activity, 0 failed to parse. The importer prints no FIT date range, and the listing cannot give one: every zip entry carries the export date as its modification time, and the names carry upload IDs, not dates. The activity FITs cover the activities up to the export date in `running.sqlite`: 1,098 activities (the export's 1,095 plus 3 kept from the API), 1,097 with records (1,094 + 3), from 2021-08-06 to 2026-10-30. The skipped non-activity FITs have no recorded date range. The same rerun gives daily summaries for 1,904 days (2021-08-08 to 2026-10-24) and Garmin metrics for 1,909 days (2021-08-07 to 2026-10-30).
- **Health data format:** JSON only, in date-window files of about 100 days each: 20 windows from 2021-05-10 to 2026-10-31 (from the file names). Resting heart rate is a field in the daily summaries (`UDSFile_*.json`), which `import-export` loads into `daily_wellness`. Sleep is in `sleepData` JSON, archived but not parsed. No file in the export is named for HRV; whether HRV sits inside the sleep files was not checked, since that needs reading their contents.

## Comments

- 2026-10-23 (from [project skeleton and dependencies](11-project-skeleton.md)): the environment variable `RUNNING_DATA_DIR` sets the data directory, default `%USERPROFILE%\running-data`. The export is extracted to `raw/export/<export date>/` in it.
- 2026-10-24: this blocks no ticket and does not block closing the map. The user requests the export on the Garmin website; once it arrives, record the Answer and close this ticket.
