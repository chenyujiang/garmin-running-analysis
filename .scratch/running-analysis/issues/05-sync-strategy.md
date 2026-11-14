# Backfill and incremental sync strategy

Type: grilling
Status: resolved
Blocked by: 01, 03, 10

## Question

How are the 5 years of history backfilled, and how is incremental sync done afterwards? The sync logic is implemented by the Rust import CLI.

- Backfill pace: what rate limit, how many batches, how to resume after an interruption.
- Incremental trigger: run a command by hand, or run it on a schedule with Windows Task Scheduler.
- How to tell "new data": by activity ID or by date, and what to do when Garmin later corrects health data (HRV, sleep).
- Behaviour and fallback (manual export) when a token expires or an API stops working.
- Training Status / VO2max / Race Predictor are fetched by the Rust CLI calling a small Python script (see [How the Rust import CLI calls the Garmin APIs](10-rust-api-coverage.md)). That script's login state is separate from the Personal API's token cache, so expiry and 429s must be handled separately for each.

## Comments

- 2026-10-23 (from [Storage design](04-storage.md)): every activity type is pulled, not just running. When Garmin later corrects a day's data, re-pulling overwrites that date's file in the raw archive. The import CLI needs a "rebuild the analysis database from the raw archive" command; when it is triggered is decided here. During an incremental sync Jupyter or the dashboard may be reading the analysis database, which SQLite's WAL mode allows.

## Answer

Decided point by point with the user on 2026-10-23. Terms are in `GLOSSARY.md`: **sync**, **backfill**, **raw archive**, **analysis database**.

**Commands** (the import CLI has only three):

- `sync`: the first run is the backfill, later runs are incremental. Each raw file is parsed and written into the analysis database as soon as it is downloaded.
- `login`: interactive garminconnect login, reading the password with `getpass` and saving only the tokens. `sync` itself never asks for a password.
- `rebuild`: deletes the analysis database and re-parses everything from the raw archive, fully offline. Run by hand only when the parsing logic changes; schema changes go through migrations, with no automatic trigger.

**Trigger**: run `sync` by hand; no Windows Task Scheduler. The reason is that when garminconnect's tokens expire the password must be typed in an interactive terminal, which a scheduled task cannot do. Switching to a scheduled task later is easy.

**Backfill pace**:

- Single-threaded, serial requests. 1.5 seconds between Personal API requests, 5 seconds between garminconnect requests. No batches; it runs to completion in one go.
- Resuming relies on the raw archive: if the raw file already exists it is skipped. After an interruption just run `sync` again; no progress file is needed.
- Daily summaries are requested in 7-day ranges, about 270 requests.
- Estimate: about 1500 activities × 2 requests, about 75 minutes.
- Garmin's three metrics backfill history weekly, one day per week, about 260 days × 3 metrics, about 1 hour. After that every sync stores a snapshot of the current day. Whether the endpoints support querying history by date is verified during implementation.

**Incremental sync**:

- New activities: page through `search_activities` from newest backwards until a page whose activities are all already in the raw archive. New activities have their details and FIT downloaded.
- Activities within the last 7 days: re-pull the detail JSON and overwrite it, because renames and type changes show up in the details. The FIT is downloaded only when missing.
- Daily summaries: every run re-pulls the last 7 days, overwrites the matching files in the raw archive, then upserts into the analysis database. The current day's data is incomplete and gets overwritten by the next sync.

**Sync state**: not stored separately; "what has already been pulled" is always inferred from the raw archive directories. The only exception is the cooldown marker files, in `state/` under the data directory.

**Credentials**: the Personal API access token is not written to disk. Each `sync` run exchanges the key for a token once (about 1.8 seconds), and again when `exp` is close.

**Failure handling** (the two data sources are independent; one failing does not affect the other):

- The Personal API token exchange fails (key expired or revoked): this source stops and the user is told to generate a new key. The current key is valid for 1 year, expiring around 2027-10.
- garminconnect's tokens expire: the small Python script ends with a dedicated exit code, and the CLI tells the user to run `login`.
- Any source returns 429 or `CAPTCHA_REQUIRED`: stop this source at once, do not retry, and write a cooldown marker in `state/`. Running `sync` again within 24 hours skips this source automatically and says why.
- When both are unavailable, the fallback is to export FIT files by hand or request an account data export (see [Request an account data export](09-account-export.md)).
