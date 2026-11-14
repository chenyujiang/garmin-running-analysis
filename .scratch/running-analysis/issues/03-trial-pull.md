# Trial pull of a small batch of real data

Type: task
Status: resolved
Blocked by: 01

## Question

Following the conclusions of the [Garmin Connect data access survey](01-garmin-data-access.md), pull a small amount of real data to see its actual shape, so the storage design can be decided:

- **Personal API**: summaries + FIT of the last ~10 running activities, plus a few days of HRV, resting heart rate and sleep. Also test how far back data can be queried.
- **`garminconnect`**: log in only once and pull Training Status, VO2max and Race Predictor once each, serially and slowly.
- **FIT comparison**: for the same activity, compare the FIT downloaded through the Personal API with the `ORIGINAL` FIT from `garminconnect` (or the original file on the watch), to confirm whether private fields are lost.

The user must create the API key and type the password to log in personally (HITL). Afterwards record in the Answer: where the API key / token are stored, the fields and file formats actually received, the earliest date reachable, the time per request, whether any rate limit was hit, and the FIT comparison result.

## Comments

- 2026-10-23: the user created a Personal API key in Garmin Connect and stored it in `.env` in the repository root (excluded by `.gitignore`).
- 2026-10-23: the old key was printed into the conversation by mistake in this session; the user revoked it and replaced it with a new key valid for 1 year. `.env` holds the bare key on one line, with no `KEY=` prefix.

## Answer

Done 2026-10-23. The scripts are in `.scratch/running-analysis/trial/`; the raw data pulled is in `trial/data/` (excluded by gitignore).

**Credentials**
- Personal API key: `.env` in the repository root, the bare key on one line, valid for 1 year (until 2027-10). The official client caches the access token in `~/.config/garmin/connect-personal-api-bearer-token.json`, valid for 24 hours.
- `garminconnect` tokens: `~/.garminconnect`. The library tightens this directory's permissions so that Git Bash cannot read it. The password was never written to disk.

**Personal API** (official client `garmin-connect-personal-api-python`, 1.5 s pause between requests)
- About 200 requests in total, no 429. The token exchange takes about 1.8 s, other requests 0.2–0.6 s.
- `search_activities`: returns a list of dicts with about 80 fields (`activityId`, `activityType.typeKey`, `startTimeLocal`, `distance`, `duration`, `averageHR`, `averageSpeed`, `elevationGain`, `hrTimeInZone_1..5`, `splitSummaries` and so on). It pages with `start`; offset 1000 still has data and 1500 is empty, so there are between 1000 and 1500 activities in total.
- `get_activity`: returns `summaryDTO`, `splitSummaries`, `metadataDTO` and more, about 3–5 KB.
- `download_activity`: returns a zip containing a single `<id>_ACTIVITY.fit` (about 94 KB; a run of about 30 minutes has about 1800 `record`s).
- **The earliest activity is on 2021-08-06**; there is no earlier data. Activity types in 2021 are running, walking, strength_training and assistance.
- Daily summaries `get_daily_summaries` return `{data: [...]}` and start at around 2021-10. Resting heart rate is in `heartRate.restingValue` and is empty on some days.
- HRV and sleep: all empty for the last 30 days (HRV returns `None`, sleep returns a dict of empty fields, `sleep_summaries` returns `[]`). The cause is that the user does not wear the watch at night, not the API.
- `get_heart_rate_zones` returns Garmin's current HRmax, LTHR and resting heart rate settings, usable as reference values.

**garminconnect 0.3.19** (5 s pause between requests)
- Login: the `mobile+cffi` and `mobile+requests` strategies both returned 429; the library fell back to later strategies and logged in successfully, 11.8 s in total. So the mobile strategies are already blocked for this machine or IP; from now on reuse the tokens as much as possible and log in as rarely as possible.
- `get_training_status`, `get_max_metrics` and `get_race_predictions` all returned normally. VO2max has `vo2MaxPreciseValue`; Race Predictor returns 5K, 10K, half-marathon and marathon times (seconds); Training Status returns `weeklyTrainingLoad`, `loadTunnelMin/Max` and `trainingStatus`.

**FIT comparison**
- 3 activities sampled: the FIT downloaded through the Personal API and the FIT downloaded through `garminconnect` `ORIGINAL` are **byte-for-byte identical**. The two zips differ only in byte 11 of the header (the file modification time).
- The FIT files keep Garmin's private messages (`unknown_233`, `unknown_325`, `unknown_104`, `unknown_140` and others) and have no developer fields.
- Conclusion: the FIT downloaded through the Personal API is the original file; there is no need to download FIT through `garminconnect`.
