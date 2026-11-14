# How the Rust import CLI calls the Garmin APIs

Type: research
Status: resolved
Blocked by: none

## Question

The import CLI is to be written in Rust, but both routes recommended by the [Garmin Connect data access survey](01-garmin-data-access.md) only have Python clients. How does the Rust side connect?

- **Personal API**: is there a ready-made Rust crate? If not, can a client be generated from the official OpenAPI document (for example `progenitor`, or `openapi-generator`'s Rust output), and how good is the generated code? How complex is a hand-written exchange of the API key for an access token?
- **Metrics only `garminconnect` has** (Training Status, VO2max, Race Predictor): is it feasible to reimplement its mobile SSO login and TLS impersonation in Rust (a Rust counterpart to `curl_cffi`, such as `rquest` / `wreq`), and how costly is it to maintain?
- If the Rust side is not worth it, the alternatives: the Rust CLI calls a small Python script responsible only for these metrics; or drop these metrics altogether (they are only a reference).
- FIT parsing: are crates such as `fitparser` still maintained, and can they read developer fields and private fields?

## Answer

The full report is `research/rust-api-coverage.md` on branch `research/rust-api-coverage` (commit `1c5df3f`). Conclusions:

- **Personal API**: no ready-made Rust crate. The official OpenAPI is 3.0.1 with 26 read-only GETs; it can only be extracted from a JS chunk of the Swagger page, and every operation lacks an `operationId`, so `progenitor` errors on it as is. Recommended: a hand-written client with `reqwest` + `serde`. Exchanging the key for a token is a single `POST .../personal-api-key/token` with header `Authorization: ApiKey <key>`; the response is a plain-text JWT whose expiry is the `exp` in its payload; with caching that is about 50 lines. To save writing the structs, add `operationId`s to the spec and have `progenitor` or `typify` generate only the models.
- **Training Status / VO2max / Race Predictor**: do not rewrite the login in Rust. The login goes through a TLS-impersonated mobile SSO and a DI OAuth2 token exchange; `wreq` on the Rust side could do it, but every blocked debugging attempt spends one login, with a risk of an account lock. The existing Rust crates (`garmin-cli`, `pulse`) all use the old OAuth1 flow that gets 429s since 2026-03. Approach: the Rust CLI calls a small PEP 723 Python script through `uv run --script`; stdout carries only JSON, and exit codes tell a 429 from an authentication failure. Pulling these three can also be postponed.
- **FIT parsing**: use `fitparser` 0.11.0, which keeps developer fields and unknown messages by default. Known issue #58: if a developer field appears before its description, the whole file fails to parse. `rustyfit` 0.11.0 is the fallback. Save the raw FIT bytes as they are first, then parse.
- **Not verified**: how progenitor handles zip responses and mixed 200/204; how long the DI refresh token lasts; whether the two FIT crates build on Windows.

## Comments

- 2026-10-23: the "trial pull of a small batch of real data" showed that FIT files downloaded through the Personal API keep many Garmin private messages (`unknown_233`, `unknown_325`, `unknown_140` and others, read with Python `fitdecode`). That largely rules out the report's last risk; the byte-for-byte comparison with the `ORIGINAL` format is recorded on the trial-pull ticket.
