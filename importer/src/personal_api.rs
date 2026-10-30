//! Garmin Connect Personal API client: the real [`ActivitySource`].
//!
//! Hand-written over blocking `reqwest`, GET endpoints only (plus the one
//! token exchange). The key from `secrets/personal_api.key` is exchanged for
//! an access token once per run and again when the token is about to expire
//! (`exp` claim of the JWT). The token is never written to disk.
//!
//! Neither the key nor the token may appear in logs or error messages: both
//! are wrapped in types whose `Debug` is redacted, header values are marked
//! sensitive, and error messages carry only the HTTP status and path.

use std::io::{Cursor, Read};
use std::path::Path;
use std::time::{Duration as StdDuration, Instant};

use anyhow::{Context, Result, anyhow, bail};
use base64::Engine;
use chrono::{DateTime, Duration, NaiveDate, NaiveDateTime, Utc};
use reqwest::StatusCode;
use reqwest::blocking::{Client, Response};
use reqwest::header::{AUTHORIZATION, HeaderValue};
use serde::Deserialize;

use crate::source::{ActivitySource, ListedActivity, SourceError};

pub const BASE_URL: &str = "https://personal.connectapi.garmin.com";
const TOKEN_PATH: &str = "/personalapitoken-service/personal-api/personal-api-key/token";
/// Exchange the key for a new token when the current one expires within this.
const RENEW_MARGIN_MINUTES: i64 = 10;
/// Used only when the token carries no readable `exp` claim.
const FALLBACK_TOKEN_LIFETIME_MINUTES: i64 = 60;

/// The Personal API key. Never printed.
pub struct ApiKey(String);

impl std::fmt::Debug for ApiKey {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("ApiKey(<redacted>)")
    }
}

impl ApiKey {
    /// Read the bare key from `path`. Errors name the file, never its content.
    pub fn load(path: &Path) -> Result<Self> {
        if !path.is_file() {
            bail!(
                "Personal API key file {} not found. Generate a key at \
                 https://connect.garmin.com/app/settings/personalApiToken and save it \
                 there (the bare key on one line).",
                path.display()
            );
        }
        let text = std::fs::read_to_string(path)
            .map_err(|e| anyhow!("reading {}: {}", path.display(), e.kind()))?;
        let key = text.trim();
        if key.is_empty() {
            bail!("Personal API key file {} is empty", path.display());
        }
        Ok(Self(key.to_owned()))
    }
}

/// An access token and its expiry. Never printed.
struct AccessToken {
    value: String,
    expires_at: DateTime<Utc>,
}

impl std::fmt::Debug for AccessToken {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "AccessToken(<redacted>, expires {})", self.expires_at)
    }
}

pub struct PersonalApiClient {
    http: Client,
    base_url: String,
    key: ApiKey,
    token: Option<AccessToken>,
    interval: StdDuration,
    last_request: Option<Instant>,
}

impl std::fmt::Debug for PersonalApiClient {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("PersonalApiClient")
            .field("base_url", &self.base_url)
            .field("interval", &self.interval)
            .finish_non_exhaustive()
    }
}

impl PersonalApiClient {
    /// Builds the client; no request is sent until the first call.
    pub fn new(key: ApiKey, interval: StdDuration) -> Result<Self> {
        let http = Client::builder()
            .user_agent(concat!("runsync/", env!("CARGO_PKG_VERSION")))
            .timeout(StdDuration::from_secs(120))
            .build()
            .context("building HTTP client")?;
        Ok(Self {
            http,
            base_url: BASE_URL.to_owned(),
            key,
            token: None,
            interval,
            last_request: None,
        })
    }

    /// Requests are serial; wait until `interval` has passed since the last.
    fn pace(&mut self) {
        if let Some(last) = self.last_request {
            let elapsed = last.elapsed();
            if elapsed < self.interval {
                std::thread::sleep(self.interval - elapsed);
            }
        }
        self.last_request = Some(Instant::now());
    }

    fn bearer(&mut self) -> Result<HeaderValue, SourceError> {
        let renew_at = Utc::now() + Duration::minutes(RENEW_MARGIN_MINUTES);
        let fresh = self.token.as_ref().is_some_and(|t| t.expires_at > renew_at);
        if !fresh {
            self.token = Some(self.exchange_key()?);
        }
        let token = self.token.as_ref().expect("token just set");
        sensitive(&format!("Bearer {}", token.value))
    }

    fn exchange_key(&mut self) -> Result<AccessToken, SourceError> {
        log::debug!("exchanging the Personal API key for an access token");
        let header = sensitive(&format!("ApiKey {}", self.key.0))?;
        self.pace();
        let response = self
            .http
            .post(format!("{}{TOKEN_PATH}", self.base_url))
            .header(AUTHORIZATION, header)
            .send()
            .map_err(|e| request_error(e, TOKEN_PATH))?;
        let response = check_status(response, TOKEN_PATH)?;
        let body = response.text().map_err(|e| request_error(e, TOKEN_PATH))?;
        let token = parse_token_response(&body)
            .ok_or_else(|| SourceError::Other(anyhow!("token response was not understood")))?;
        let expires_at = jwt_expiry(&token).unwrap_or_else(|| {
            log::warn!("access token has no readable exp claim; renewing it within the hour");
            Utc::now() + Duration::minutes(FALLBACK_TOKEN_LIFETIME_MINUTES)
        });
        log::info!("got a Personal API access token, valid until {expires_at}");
        Ok(AccessToken {
            value: token,
            expires_at,
        })
    }

    fn get(&mut self, path: &str) -> Result<Response, SourceError> {
        let bearer = self.bearer()?;
        self.pace();
        log::debug!("GET {path}");
        self.http
            .get(format!("{}{path}", self.base_url))
            .header(AUTHORIZATION, bearer)
            .send()
            .map_err(|e| request_error(e, path))
    }
}

impl ActivitySource for PersonalApiClient {
    fn list_activities(
        &mut self,
        start: usize,
        limit: usize,
    ) -> Result<Vec<ListedActivity>, SourceError> {
        let path = format!(
            "/activitylist-service/activities/search/activities?start={start}&limit={limit}"
        );
        let response = check_status(self.get(&path)?, &path)?;
        let body = response.text().map_err(|e| request_error(e, &path))?;
        let items: Vec<ListItem> = serde_json::from_str(&body)
            .with_context(|| format!("parsing the activity list from {path}"))?;
        items
            .into_iter()
            .map(|item| {
                Ok(ListedActivity {
                    activity_id: item.activity_id,
                    start_time_utc: parse_gmt(&item.start_time_gmt)?,
                })
            })
            .collect()
    }

    fn activity_detail(&mut self, activity_id: i64) -> Result<String, SourceError> {
        let path = format!("/activity-service/activity/{activity_id}");
        let response = check_status(self.get(&path)?, &path)?;
        response.text().map_err(|e| request_error(e, &path))
    }

    fn activity_fit(&mut self, activity_id: i64) -> Result<Option<Vec<u8>>, SourceError> {
        let path = format!("/download-service/files/activity/{activity_id}");
        let response = self.get(&path)?;
        if response.status() == StatusCode::NOT_FOUND {
            log::info!("activity {activity_id} has no file to download");
            return Ok(None);
        }
        let response = check_status(response, &path)?;
        let bytes = response.bytes().map_err(|e| request_error(e, &path))?;
        let fit = extract_fit(&bytes)
            .with_context(|| format!("unpacking the download of activity {activity_id}"))?;
        if fit.is_none() {
            log::warn!("activity {activity_id}: the download holds no FIT file");
        }
        Ok(fit)
    }

    fn daily_summaries(&mut self, start: NaiveDate, end: NaiveDate) -> Result<String, SourceError> {
        let path = format!(
            "/usersummary-service/v2/dailysummaries?startDate={}&endDate={}",
            start.format("%Y-%m-%d"),
            end.format("%Y-%m-%d")
        );
        let response = check_status(self.get(&path)?, &path)?;
        response.text().map_err(|e| request_error(e, &path))
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct ListItem {
    activity_id: i64,
    #[serde(rename = "startTimeGMT")]
    start_time_gmt: String,
}

/// `2026-10-07 22:08:46` (activity list) or `2026-10-07T22:08:46.0`.
fn parse_gmt(raw: &str) -> Result<DateTime<Utc>, SourceError> {
    NaiveDateTime::parse_from_str(raw, "%Y-%m-%d %H:%M:%S%.f")
        .or_else(|_| NaiveDateTime::parse_from_str(raw, "%Y-%m-%dT%H:%M:%S%.f"))
        .map(|t| t.and_utc())
        .map_err(|_| SourceError::Other(anyhow!("unrecognised startTimeGMT {raw:?}")))
}

fn sensitive(value: &str) -> Result<HeaderValue, SourceError> {
    let mut header = HeaderValue::from_str(value)
        .map_err(|_| SourceError::Other(anyhow!("credential contains invalid characters")))?;
    header.set_sensitive(true);
    Ok(header)
}

/// Map an HTTP status to the three error kinds. Bodies are never put into
/// error messages.
fn check_status(response: Response, path: &str) -> Result<Response, SourceError> {
    let status = response.status();
    if status.is_success() {
        return Ok(response);
    }
    if status == StatusCode::TOO_MANY_REQUESTS {
        return Err(SourceError::RateLimited(format!("HTTP 429 from {path}")));
    }
    if status == StatusCode::UNAUTHORIZED || status == StatusCode::FORBIDDEN {
        let body = response.text().unwrap_or_default();
        if body.contains("CAPTCHA_REQUIRED") {
            return Err(SourceError::RateLimited(format!(
                "CAPTCHA_REQUIRED from {path}"
            )));
        }
        return Err(SourceError::CredentialsRejected);
    }
    Err(SourceError::Other(anyhow!("HTTP {status} from {path}")))
}

/// `reqwest` errors name the URL, which holds no credentials; strip it
/// anyway and keep only the path.
fn request_error(err: reqwest::Error, path: &str) -> SourceError {
    let kind = if err.is_timeout() {
        "timed out"
    } else if err.is_connect() {
        "could not connect"
    } else if err.is_decode() || err.is_body() {
        "could not read the response"
    } else {
        "request failed"
    };
    SourceError::Other(anyhow!("{kind}: {path}"))
}

/// The token endpoint answers with a bare JWT; accept a JSON object with
/// `access_token` / `accessToken` too.
fn parse_token_response(body: &str) -> Option<String> {
    let body = body.trim();
    if body.starts_with('{') {
        let v: serde_json::Value = serde_json::from_str(body).ok()?;
        let token = v.get("access_token").or_else(|| v.get("accessToken"))?;
        return token.as_str().map(str::to_owned);
    }
    let body = body.trim_matches('"');
    (!body.is_empty() && !body.contains(char::is_whitespace)).then(|| body.to_owned())
}

/// The `exp` claim of a JWT, without verifying it.
fn jwt_expiry(token: &str) -> Option<DateTime<Utc>> {
    let payload = token.split('.').nth(1)?;
    let bytes = base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(payload.trim_end_matches('='))
        .ok()?;
    let claims: serde_json::Value = serde_json::from_slice(&bytes).ok()?;
    DateTime::from_timestamp(claims.get("exp")?.as_i64()?, 0)
}

/// The download is a zip holding the original file. Return its single FIT
/// entry (the zip is dropped). A bare FIT is passed through.
fn extract_fit(bytes: &[u8]) -> Result<Option<Vec<u8>>> {
    if bytes.get(8..12) == Some(b".FIT") {
        return Ok(Some(bytes.to_vec()));
    }
    let mut zip = zip::ZipArchive::new(Cursor::new(bytes)).context("not a zip file")?;
    let fit_entries: Vec<usize> = (0..zip.len())
        .filter(|&i| {
            zip.name_for_index(i)
                .and_then(|n| n.ok())
                .is_some_and(|n| n.to_ascii_lowercase().ends_with(".fit"))
        })
        .collect();
    match fit_entries.as_slice() {
        [] => Ok(None),
        [i] => {
            let mut entry = zip.by_index(*i)?;
            let mut fit = Vec::with_capacity(entry.size() as usize);
            entry.read_to_end(&mut fit)?;
            Ok(Some(fit))
        }
        many => bail!("zip holds {} FIT files, expected one", many.len()),
    }
}
