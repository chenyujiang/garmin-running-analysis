# 07: Rate-limit cooldown and expired credentials

**What to build:** When one data source is rate-limited or its credentials have expired, `runsync sync` stops that source safely and tells the user why and how to fix it; the other source finishes as usual.

**Blocked by:** 04 (Personal API activity sync), 06 (small garminconnect script: `login` and the three Garmin metrics)

**Status:** done

Source: User Stories 19–24 in the [implementation spec](../spec.md).

- [x] On a 429 or `CAPTCHA_REQUIRED`, stop this source at once without retrying
- [x] Write a cooldown marker in `state/` with the time and the reason; a `sync` within 24 hours skips this source and says why and when it resumes; after 24 hours it resumes on its own
- [x] The two sources run serially and independently: an error in one does not affect the other
- [x] When the garminconnect tokens have expired, suggest running `runsync login`; when the Personal API key is rejected, suggest generating a new key (it expires around 2027-10)
- [x] `sync` never asks for a password
- [x] Seam 2 tests: a cooldown marker is written after a rate limit; the source is skipped during the cooldown; it resumes after 24 hours; when one source fails the other finishes as usual; each of the two credential failures prints its own hint

## Outcome

- New module `runsync::cooldown`: marker file `state/<source>.cooldown.json` with fields `source`, `since_utc`, `until_utc` (ISO with a `Z`) and `reason` (such as `rate limited (HTTP 429)`). `cooldown::active(data_dir, source, now)` deletes the marker and returns `None` once it has expired (`now >= until_utc`), so it resumes on its own after 24 hours; deleting the marker by hand resumes early. When the marker cannot be parsed, this source reports an error (suggesting to delete the marker) instead of being treated as not in cooldown.
- New module `runsync::sync_all`: `sync_all(data_dir, &SyncOptions, personal_api: anyhow::Result<&mut dyn ActivitySource>, garminconnect: Option<&mut dyn MetricsSource>) -> SyncAllReport`. Personal API first, then garminconnect, serially and independently. Each source's result is `Outcome::{Done, Skipped, Failed}(message)`, with the message starting with the source name. `report.success()` is false only when there is a `Failed`.
- The cooldown marker is checked before the source is used: during a cooldown no request is sent and no key is needed (a missing key file is skipped the same way, without an error). A cooldown skip and a no-token skip are not failures; the exit code is 0.
- Rate limit (`SourceError::RateLimited`, covering 429 and `CAPTCHA_REQUIRED`): write the marker, and print the reason, the part already done, the resume time (local time with offset) and the marker path. Expired credentials and other errors write no marker.
- `main.rs` only builds the two sources (no network and no script start while building) and prints the result of `sync_all`; `Done`/`Skipped` go to stdout and `Failed` to stderr (`error: ...`), and any failure gives exit code 1.
- `sync` never asks for a password: the Personal API only reads the key file; garminconnect only uses `serve` (stdin is the protocol pipe, and only tokens are loaded); the interactive `getpass` exists only in `runsync login`.
- Deviation: `tdd` asks to confirm the seam with the user first; here the spec's Seam 2 (`sync_all` against two fake sources) was used directly, plus one CLI test (the cooldown marker makes `runsync sync` skip the Personal API).
- Tests: `importer/tests/sync_all.rs` (11 tests); `importer/tests/cli.rs` gains 1.
