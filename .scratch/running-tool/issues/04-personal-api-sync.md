# 04: Personal API activity sync

**What to build:** When the user runs `runsync sync`, every activity on the Personal API (all types) is downloaded into the raw archive and written into the analysis database at the same time. If interrupted, running it again continues from where it stopped; later runs pull only new activities plus those of the last 7 days.

**Blocked by:** 03 (FIT parsing into `records` and `laps`)

**Status:** done

Source: User Stories 3, 9–14, 16, 18, 25 and 26, and "Data source trait", "Personal API client", "Raw archive layout" and "Sync algorithm" under Implementation Decisions, in the [implementation spec](../spec.md).

- [x] Define a data source trait that the sync logic depends on exclusively; errors are a small enum of three kinds: rate limit, rejected credentials, other
- [x] The Personal API client is hand-written with `reqwest` (blocking): each run exchanges the key for an access token once, takes the expiry from the JWT's `exp`, and exchanges again when it is close to expiring; the token is not written to disk; neither key nor token appears in logs
- [x] The activity list is paged from newest backwards until a page whose activities are all already in the raw archive
- [x] The detail JSON and the FIT (a zip; the single FIT inside is extracted and the zip discarded) are downloaded and stored in the raw archive as they are; each downloaded file is parsed and written to the database right away
- [x] Resuming looks only at whether the raw files already exist; no progress is stored
- [x] Activities from the last 7 days have their detail JSON re-pulled and overwritten; the FIT is downloaded only when missing
- [x] Requests are sent serially, with the interval from `config.toml`, default 1.5 s
- [x] The backfill shows an `indicatif` progress bar; `RUST_LOG` controls the log level
- [x] During a sync, Jupyter or the dashboard can open the analysis database read-only at the same time (WAL)
- [x] Seam 2 tests: drive `sync` with an in-memory fake data source and assert that existing raw files are skipped, paging stops when a whole page already exists, and the details of the last 7 days are overwritten; real HTTP is not tested

## Outcome

- **Modules**: `importer/src/source.rs` (the `ActivitySource` trait, `ListedActivity`, `SourceError { RateLimited(String), CredentialsRejected, Other(anyhow::Error) }`); `importer/src/sync.rs` (`sync_activities(&DataDir, &mut dyn ActivitySource, &SyncOptions) -> Result<SyncReport>`); `importer/src/personal_api.rs` (`ApiKey`, `PersonalApiClient`).
- **What "already exists" means**: each activity downloads its FIT first and its detail JSON second, so an existing `<id>.json` means the activity is complete. When interrupted between the two, the next run only adds the JSON. Every file is written as `.part` first and then renamed, so the archive never holds half a file.
- **Activities without a FIT** (manual entries and the like): when the download endpoint returns 404, or the zip has no `.fit`, only the JSON is stored. When the download is itself a FIT (not a zip), it is stored as is.
- **Paging**: stop when every activity on a page already has its JSON; but if the oldest activity on that page is still within the last 7 days, keep paging so the 7-day window is complete. Page size 100.
- **Errors**: any data source error stops this source at once, keeps what was downloaded, records `rate_limited` / `auth_failed` / `error` in `sync_runs`, and the CLI exits 1 with a hint. 401/403 counts as rejected credentials; a 401/403 response body containing `CAPTCHA_REQUIRED` counts as a rate limit. Cooldown markers are left to ticket 07.
- **Credentials**: the key and token types print `<redacted>` in `Debug`, request headers are marked sensitive, and error messages contain only the HTTP status and path, not the response body. The token lives only in memory; it is exchanged again when less than 10 minutes remain before `exp`; when the JWT has no readable `exp`, it is treated as 1 hour. The token endpoint's response is accepted both as a plain-text JWT and as JSON containing `access_token`.
- **Config**: `config.toml` gains `[sync] personal_api_interval_s`, default 1.5.
- **Not verified**: real HTTP was never called (not tested, by the rules). The format of `startTimeGMT` in the activity list, the FIT zip structure and the token response format follow the survey and the official Swagger, and must be confirmed on the first real run (ticket 08).
