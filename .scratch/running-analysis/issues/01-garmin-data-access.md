# Survey of ways to get data out of Garmin Connect

Type: research
Status: resolved
Blocked by: none

## Question

As of 2026, what is the most workable way to pull one's own data, as an individual, from international Garmin Connect (MFA not enabled)?

Specifically, find out:

- Are unofficial libraries such as `garminconnect` / `garth` still maintained and working? The login flow, where tokens are stored and how long they last.
- Which data is available: the activity list, raw FIT downloads (per-second data streams), HRV, resting heart rate, sleep, and Garmin's own Training Load, VO2max and Race Predictor.
- Known rate-limit and account-lock behaviour: how slow must a 5-year backfill be to stay safe?
- Fallback: what the account data export (Garmin's data export request) contains, in what format, and whether it covers the data above.

## Answer

Detailed survey (with a source for every point): `research/garmin-data-access.md` on branch `research/garmin-data-access` (commit `031a024`, local only).

- **Main route: the official Garmin Connect Personal API** (released 2026-10-21, official Python client `garmin/connect-personal-api-python` v1.0.0). Read-only; an API key (valid 30 days to 1 year) is exchanged for a 24-hour access token, with no refresh token. Covers the activity list/details, FIT downloads (zip), HRV, sleep and daily summaries (including `restingHeartRate`). It does **not** cover Training Status, the VO2max trend or Race Predictor.
- **`garth` is deprecated** (2026-03-28): Garmin changed the login flow, and since 2026-03-17 new logins get a Cloudflare 429.
- **`garminconnect` is still maintained** (0.3.19, 2026-10-16). Use it to fill in `get_training_status`, `get_max_metrics_range` and `get_race_predictions`. Tokens are stored in `~/.garminconnect/garmin_tokens.json`. Raw FIT needs `ActivityDownloadFormat.ORIGINAL`. The library itself does not throttle; known 429s mostly hit the login step, and one account was locked for 48–72 hours or more. Usage: log in only once, go serially and slowly, and stop at the first 429/403.
- **Account data export**: its FIT files are byte-for-byte the files on the watch, a fallback raw archive of the 5-year history. The format of the health data in the export could not be confirmed.
- **Open risks**: how far back the Personal API reaches and its rate limits are not published; FIT files downloaded through the API may be rewritten and lose private fields (to be tested); the unofficial login may break again at any time.
