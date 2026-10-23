# Rust 导入 CLI 如何调用 Garmin 接口

调研日期：2026-10-23。对应 ticket：`.scratch/running-analysis/issues/10-rust-api-coverage.md`。
前置结论见 `01-garmin-data-access.md`：主力用官方 Personal API，Training Status / VO2max / Race Predictor 只能靠 `cyberjunky/python-garminconnect`。

## 1. Personal API 的 Rust 接入

### 1.1 没有现成 crate

- crates.io 搜 `garmin` 共 45 个 crate，没有一个对接 Personal API（`personal.connectapi.garmin.com`）。搜 `garmin personal`、`garmin connect`、`connectapi` 也没有。来源：https://crates.io/api/v1/crates?q=garmin&per_page=50 ，https://crates.io/api/v1/crates?q=garmin%20connect
- GitHub 代码搜索在 Rust 代码里找不到 `personal.connectapi.garmin.com`（`gh search code "personal.connectapi.garmin.com" --language rust` 结果为空）。
- 官方 Python 客户端是手写的，不是生成的。README 说 wrapper "may lag behind new endpoints"，并提供通用的 `get()`。来源：https://github.com/garmin/connect-personal-api-python

### 1.2 OpenAPI spec 的实际情况

- Swagger 页面 https://developer.garmin.com/gc-developer-program/personal/swagger-docs/ 没有可下载的 JSON/YAML 链接。spec 内联在页面 chunk 里：`https://developer.garmin.com/component---src-pages-gc-developer-program-personal-swagger-docs-js-178270c98d5ec74e74ef.js`，形式是 `JSON.parse('{"openapi":"3.0.1",...}')`。文件名带构建 hash，Garmin 每次重新构建后 URL 都会变。要写个小脚本提取：找到这个字符串字面量，处理 JS 转义后再按 JSON 解析。
- 实际提取后的统计：
  - `openapi: 3.0.1`，`info.version: 1.0.0`，`servers: https://personal.connectapi.garmin.com`
  - 26 条 path，全部是 GET；`components.schemas` 有 109 个
  - 没有 `securitySchemes` 和 `security`。token 端点和 Bearer 认证都不在 spec 里
  - **所有 operation 都没有 `operationId`**
  - `allOf` 出现 66 次，都是"单个 `$ref` + `description`/`example`"的包装写法。没有 `oneOf`、`anyOf`、`discriminator`
  - `nullable` 34 处；`additionalProperties` 3 处（map 类型）；`format` 用到 date、date-time、double、float、int32、int64、uuid，另有 1 处非标准的 `time`
  - 下载端点 `/download-service/files/activity/{activityId}` 只定义了 `default` 响应，content type 是 `application/x-zip-compressed`，没有 schema
  - `/hrv-service/hrv/{calendarDate}` 和 `/hrv-service/hrv/daily/...` 同时定义了 `200`（JSON）和 `204`（空）
- 与官方 Python 客户端对比：spec 多出 `/usersummary-service/usersummary/daily` 和 `/weight-service/weight/all/...` 两条；客户端的 wrapper 有 24 个。来源：https://github.com/garmin/connect-personal-api-python

### 1.3 生成器能否处理

**`progenitor`**（oxidecomputer，0.15.1，2026-10-09，来源 https://crates.io/crates/progenitor ）

- 只接受 3.0.x。`validate_openapi_spec_version` 检查的是 `starts_with("3.0.")`，所以 3.0.1 没问题。来源：https://github.com/oxidecomputer/progenitor/blob/main/progenitor-impl/src/lib.rs
- `validate_openapi` 要求每个 operation 都有 `operationId`，缺了就报 `path {} is missing operation ID`（同一文件）。**Garmin 的 spec 原样喂进去会直接失败。** 需要先预处理，比如用 jq 或 Python 按 `{tag}_{path}` 生成 ID。26 个端点，也可以手写一张映射表。
- 请求体的 content type 只认 `application/octet-stream`、`application/json`、`application/x-www-form-urlencoded`、`text/plain`。来源：https://github.com/oxidecomputer/progenitor/blob/main/progenitor-impl/src/method.rs 。这个 API 没有请求体，不受影响。响应如果不是 JSON，代码里走另一条分支（`response.content.first().is_some()`）。**未验证**：下载端点只有 `default` 响应，HRV 端点 200/204 混用，这两种情况生成出来的返回类型是否顺手，需要实际跑一次确认。
- 类型生成由 typify 负责。单 `$ref` 的 `allOf` 包装、`nullable`、map 型 `additionalProperties` 都属于常见写法。**推测**：能生成，但字段大量是 `Option<T>`，非标准的 `format: time` 会退化成 `String`。

**`openapi-generator` 的 `rust` 生成器**（7.26.0，2026-10-06，来源 https://github.com/OpenAPITools/openapi-generator/releases ）

- 缺 `operationId` 时，`DefaultCodegen.getOrGenerateOperationId` 会按 path + method 自动生成，不会报错。来源：https://github.com/OpenAPITools/openapi-generator/blob/master/modules/openapi-generator/src/main/java/org/openapitools/codegen/DefaultCodegen.java 。**推测**：生成的方法名会很长、不好看。
- 文档把它标为 "Generates a Rust client library (beta)"。可选 `reqwest`（默认）、`reqwest-trait`、`hyper` 等库，默认 `supportAsync=true`。来源：https://github.com/OpenAPITools/openapi-generator/blob/master/docs/generators/rust.md
- 需要 Java 运行时，生成的是一个完整 crate（models/apis 目录），对学 Rust 的人来说噪音偏多。

**评估**：只有 26 个只读 GET，生成器省下的工作不多。手写客户端反而是学 `reqwest` + `serde` 的好练习。折中办法是用生成器只产出 model 结构体（progenitor 或 `typify` 读 `components.schemas`），HTTP 层自己写。

### 1.4 API key 换 access token：很简单

官方客户端的实现（来源：https://github.com/garmin/connect-personal-api-python/blob/main/src/garmin_personal_api/auth.py 和 `constants.py`）：

- `POST https://personal.connectapi.garmin.com/personalapitoken-service/personal-api/personal-api-key/token`
- 请求头 `Authorization: ApiKey <key>`、`Accept: */*`，无请求体
- 响应体是**纯文本 JWT**（`response.text.strip()`），不是 JSON。过期时间从 JWT payload 的 `exp` 读，不验签
- 缓存文件 `~/.config/garmin/connect-personal-api-bearer-token.json`，存 `fingerprint`（`sha256(base_url \0 key)`）、`access_token`、`expires_at`。剩余有效期不到 1 小时就重新换
- 数据请求只带 `Authorization: Bearer <token>`，用普通 `requests`，没有 TLS 伪装（同仓库 `client.py`）
- key 在 https://connect.garmin.com/app/settings/personalApiToken 创建，只显示一次。来源：https://developer.garmin.com/gc-developer-program/personal/personal-api/

Rust 示意（依赖 `reqwest`、`base64`、`serde_json`）：

```rust
async fn obtain_token(http: &reqwest::Client, key: &str) -> anyhow::Result<(String, i64)> {
    let jwt = http
        .post("https://personal.connectapi.garmin.com/personalapitoken-service/personal-api/personal-api-key/token")
        .header("Authorization", format!("ApiKey {key}"))
        .header("Accept", "*/*")
        .send().await?.error_for_status()?.text().await?.trim().to_owned();
    let payload = jwt.split('.').nth(1).ok_or_else(|| anyhow::anyhow!("not a JWT"))?;
    let claims: serde_json::Value = serde_json::from_slice(
        &base64::engine::general_purpose::URL_SAFE_NO_PAD.decode(payload.trim_end_matches('='))?)?;
    Ok((jwt, claims["exp"].as_i64().unwrap_or_default()))
}
```

加上缓存文件读写，总共约 50 行。

## 2. 在 Rust 里重写 python-garminconnect 的登录

### 2.1 0.3.19 的登录流程（读源码）

来源：https://github.com/cyberjunky/python-garminconnect/tree/master/garminconnect/client （`sso.py`、`session.py`、`constants.py`、`transport.py`）

1. **5 个策略依次尝试**（`sso.py` 的 docstring）：
   1. `mobile+cffi`：iOS 移动端 SSO，用 `curl_cffi` 并轮换 TLS 指纹 `("safari_ios", "safari", "chrome120")`
   2. `mobile+requests`：同一流程，用普通 `requests`
   3. `widget+cffi`：SSO embed HTML 表单流程，需要抓 `_csrf`
   4. `portal+cffi`：网页 portal 流程，GET 和 POST 之间随机等 10–20 秒（`LOGIN_DELAY_*`）
   5. `portal+requests`：最后兜底
2. **mobile 流程**：`POST https://sso.garmin.com/mobile/api/login?clientId=GCM_IOS_DARK&locale=en-US&service=https://mobile.integration.garmin.com/gcm/ios`
   - 请求头：iPhone Safari UA、`Origin: https://sso.garmin.com`
   - JSON 体：`{"username","password","rememberMe":true,"captchaToken":""}`
   - 响应 `responseStatus.type` 可能是 `SUCCESSFUL`（带 `serviceTicketId`）、`MFA_REQUIRED`、`INVALID_USERNAME_PASSWORD` 或 `CAPTCHA_REQUIRED`
   - 429 和 403 都当作被拦截，接着试下一个策略
3. **ticket 换 token**（`session.py::_exchange_service_ticket`）：`POST https://diauth.garmin.com/di-oauth2-service/oauth/token`
   - form 字段：`grant_type=https://connectapi.garmin.com/di-oauth2-service/oauth/grant/service_ticket`、`client_id`、`service_ticket`、`service_url`
   - `client_id` 依次尝试 `GARMIN_CONNECT_MOBILE_ANDROID_DI_2025Q2`、`..._2024Q4`、`..._DI`、`GARMIN_CONNECT_MOBILE_IOS_DI`，并用它做 Basic auth
   - 请求头带 `User-Agent: GCM-Android-5.23` 和 `X-Garmin-User-Agent`
   - 有 curl_cffi 时，这一步用 `impersonate="chrome"` 发出（`_http_post`）
   - 返回 `access_token` 和 `refresh_token`；之后用 `grant_type=refresh_token` 刷新（`_refresh_di_token`）
   - 存到 `garmin_tokens.json`（`tokens.py`）。**未知**：refresh token 的有效期，源码里没写
4. **数据请求**：`https://connectapi.garmin.com/...`，带 `Authorization: Bearer <di_token>` 和移动端 UA，用的是**普通 `requests.Session`**（`client/__init__.py` 里的 `_api_session`）
   - issue #444 曾怀疑数据请求也需要伪装，最后查明是用户 `~/.netrc` 覆盖了 Authorization 头。作者确认 API 请求"have always used plain `requests`"。来源：https://github.com/cyberjunky/python-garminconnect/issues/444
5. **三项指标的端点**（`api/base.py`、`api/metrics.py`）：
   - Training Status：`/metrics-service/metrics/trainingstatus/aggregated/{date}`（另有 `/daily/{date}` 和 `/weekly/{displayName}`）
   - VO2max：`/metrics-service/metrics/maxmet/daily/{start}/{end}`（另有 `/maxmet/latest/{date}`）
   - Race Predictor：`/metrics-service/metrics/racepredictions/latest/{displayName}`

**为什么需要 TLS 伪装**：
- 没装 curl_cffi 时库会警告，说 plain-requests fallbacks "are usually blocked by Cloudflare"（`sso.py`）
- issue #453：只用 `mobile+requests` 时，第一个请求就收到 429。作者解释 429 "based on the client fingerprint"，不只看 IP。来源：https://github.com/cyberjunky/python-garminconnect/issues/453
- `constants.py` 的注释也说 "Cloudflare flags rapid GET→POST sequences as bot-like"

结论：**只有登录（SSO 和 DI 换 token）需要伪装**。拿到 DI token 和 refresh token 后，日常数据请求用普通 HTTP 客户端就行。

### 2.2 Rust 的 TLS 伪装方案

- **`wreq`** 0.16.1（2026-08-27），作者 0x676e67，Apache-2.0，1079 stars，2026-10-23 仍有提交。来源：https://crates.io/crates/wreq ，https://github.com/0x676e67/wreq
  - 0.16.0 是原 `6.0.0-rc.*` 线的正式版，版本号重置过，从 5.x 升级是破坏性变更。MSRV 1.98。TLS 后端换成了 `btls`（BoringSSL fork）。来源：https://github.com/0x676e67/wreq/releases/tag/v0.16.0
  - 浏览器配置由 `wreq-util` 0.2.0（2026-08-22）提供，README 说有 100+ 个，包括 `safari_ios_16_5`、`safari_ios_17_2`、`safari_ios_18_1_1`、`safari26_*` 等。来源：https://github.com/0x676e67/wreq-util/blob/main/src/emulate/profile/safari.rs
  - **Windows**：主 CI 的 Build job 有 `windows-latest`（https://github.com/0x676e67/wreq/blob/main/.github/workflows/ci.yml ）。编译指南要求先 `choco install cmake strawberryperl pkgconfiglite llvm nasm`（https://github.com/0x676e67/wreq/blob/main/.github/compilation-guide/build.yml ）。README 提醒和 `openssl-sys` 一起链接可能有符号冲突，可开 `prefix-symbols`。
- **`rquest`**：已改名为 `wreq`。crates.io 上 5.x 全部 yanked，最新显示 0.0.0。来源：https://crates.io/api/v1/crates/rquest 。`reqwest-impersonate` 同样只剩 0.0.0。不要用这两个。
- **维护成本**：伪装的效果取决于 Garmin/Cloudflare 的指纹策略。Python 侧 0.3.0 到 0.3.19 半年内发了约 20 个版本，持续在调整策略链，Rust 侧得自己跟进。

### 2.3 现有 Rust Garmin Connect crate

- **`garmin-cli`** 2.2.0（2026-10-19，56 stars）。来源：https://github.com/vicentereig/garmin-cli
  - 命令覆盖 training status、VO2max、race predictions，测试 fixture 里有 `training_status.json`、`vo2max.json`、`race_predictions.json`
  - 登录在 `src/client/sso.rs`：先走 `sso.garmin.com/mobile/api/login`（client ID `GCM_ANDROID_DARK`），再走 garth 式的 OAuth1 `connectapi.garmin.com/oauth-service/oauth/preauthorized`，consumer key 来自 `thegarth.s3.amazonaws.com`，最后换 OAuth2
  - 用普通 `reqwest` + `rustls-tls`，**没有 TLS 伪装**（见 Cargo.toml）
  - preauthorized 端点正是 2026-03 起被 429 的那个（https://github.com/cyberjunky/python-garminconnect/issues/337 ）。garth 也因同一原因弃用（https://github.com/matin/garth ）
  - **未验证**：新账号能否用它登录成功。它的 issue 里没有登录失败的报告，但作者可能在用旧 token
  - 官方 release 只提供 macOS/Linux 二进制
- **`pulse-health-core` / `pulse-cli`** 0.14.0（2026-10-19）。`auth.rs` 用旧的 `sso.garmin.com/sso` + OAuth1（thegarth consumer），依赖 `reqwest` 0.13，同样没有伪装，属于 garth 已失效的老流程。来源：https://github.com/selcux/pulse
- **`garmin_client` / `garmin_download`** 0.2.1（2024-12），已停更。来源：https://crates.io/crates/garmin_client

**结论**：Rust 里没有采用当前有效流程（TLS 伪装 + DI OAuth2）的库。可以参照 python-garminconnect 移植：一条 mobile 策略、DI 换 token、refresh，大约几百行。**难点不在代码量，而在调试被拦截的情况。** 每次失败都要消耗一次登录机会，失败多了可能锁号（见 01 号调研）。

## 3. 备选：Rust 调 Python 小脚本

- 写一个 `garmin_metrics.py`，用 PEP 723 内联依赖声明 `garminconnect==0.3.19`。Rust 用 `std::process::Command` 执行 `uv run --script garmin_metrics.py --start .. --end ..`，读取 stdout 的 JSON。`uv lock --script` 可以锁住版本。来源：https://docs.astral.sh/uv/guides/scripts/
- 注意事项：
  - garminconnect 要求 Python ≥ 3.12，依赖 `curl_cffi>=0.15.0`（https://pypi.org/pypi/garminconnect/json ）。curl_cffi 0.16.3 有 `win_amd64` wheel，Windows 不用编译（https://pypi.org/pypi/curl-cffi/json ）
  - 登录状态在 `~/.garminconnect/garmin_tokens.json`，和 Personal API 的缓存各管各的。首次登录或输入 MFA 要单独交互运行脚本
  - 约定好协议：stdout 只输出 JSON，日志写 stderr；用退出码区分 429 和认证失败，Rust 侧遇到 429 立即停止，不重试
  - 机器上要同时有 Rust 工具链和 uv。可以接受，因为分析部分本来就用 Python
- 还有一个更简单的选择：干脆不拉这三项指标。它们只是 Garmin 自己的参照值，不影响核心分析。

## 4. FIT 解析 crate

| crate | 最新版本 | 关键事实 |
|---|---|---|
| `fitparser` | 0.11.0，2026-05-01 | 88.9k 下载，73 stars。FIT SDK profile 21.202.0。只读，不能写。依赖只有 `chrono`、`nom`、`serde`，纯 Rust |
| `rustyfit` | 0.11.0，2026-10-19 | `#![no_std]`，能读也能写，profile v21.218，可选 serde，BSD-3。由 Go 库 `muktihari/fit` 改写 |
| `fit-sdk-rust` | 0.2.1，2026-05-25 | 创建于 2026-05，0 stars。功能列表很全，含开发者字段解析，但太新、没人用 |
| `fit_file`、`fit-rust`、`garminfit`、`fitparse` | 2018–2023 | 已停更 |

来源：https://crates.io/crates/fitparser ，https://github.com/stadelmanma/fitparse-rs ，https://github.com/muktihari/rustyfit ，https://github.com/Chen-Lim/fit-sdk-rust ，https://crates.io/api/v1/crates?q=garmin&per_page=50

- **`fitparser` 的开发者字段**：README 写明 "Files with Developer Data fields can be parsed and the developer fields are correctly extracted"。没有描述的开发者字段命名为 `unknown_developer_field_{n}`（`src/lib.rs`）。
- **`fitparser` 的未知/私有消息**：默认保留，可以用 `DecodeOption::DropUnknownFields` / `DropUnknownMessages` 主动丢弃（`src/de/mod.rs`）。所以 Garmin 私有消息会以数字编号的形式保留下来。
- **`fitparser` 的已知 bug**：issue #58（2026-08-23，未关闭）。如果 definition 引用的开发者字段比它的 `field_description` 先出现，**整个文件**会以 `Fail` 中止。报告里的例子是 Hammerhead Karoo。**未验证**：Garmin 手表录的文件是否会这样，FIT 规范要求描述在前。来源：https://github.com/stadelmanma/fitparse-rs/issues/58
- **`rustyfit`**：`Message` 包含 `num`、`fields`、`developer_fields`，解码时读取 `DeveloperFieldDefinition`（`rustyfit/src/proto.rs`、`decoder/mod.rs`）。**未验证**：开发者字段能否自动解析成名称和单位。
- **Windows**：两个都是纯 Rust，没有 C 依赖，理论上没有构建问题。但两者 CI 都只跑 `ubuntu-latest`（各自的 `.github/workflows/ci.yml`），Windows 没有官方验证。

## 建议

1. **Personal API**：用 `reqwest` + `serde` 手写客户端，token 换取约 50 行，26 个端点按需实现。想省写结构体的功夫，可以先给 spec 补上 `operationId`，再用 `progenitor`（或只用 typify 生成 models）。不推荐 `openapi-generator` 的 rust 生成器：beta、要 Java、输出冗余。
2. **三项指标**：不要在 Rust 里重写登录。用 Rust 调 `uv run` Python 小脚本的方案，或者先不拉这三项。如果以后想把这个当 Rust 练习，用 `wreq` + `wreq-util` 移植一条 mobile 策略和 DI token 流程，不要基于 `garmin-cli` 或 `pulse` 的 OAuth1 流程。
3. **FIT**：用 `fitparser` 0.11.0，保持默认（不丢未知字段和消息）。准备一个 `rustyfit` 的回退路径，遇到 #58 那类文件时用。
4. **存原始字节**：ingest 时先原样保存 FIT 字节，再解析。这样解析库换了或出 bug，都不会丢数据。

## 未决风险

- spec 没有独立 URL，只能从 hash 命名的 JS chunk 里提取，Garmin 改版后要重新提取。spec 里也没写认证方式、限流和可回溯的历史范围。
- progenitor 对 `default`-only 的 zip 响应、200/204 混用的处理**未实测**。
- DI refresh token 的有效期未知。Garmin 的指纹策略随时可能变，现在的伪装配置可能失效。
- `garmin-cli` 能否用于新登录未验证。
- `fitparser` #58 是否影响 Garmin 手表文件、两个 FIT crate 在 Windows 上的实际构建情况，都未验证。
- Personal API 下载的 FIT 是否保留私有字段，仍待实测（见 01 号调研）。
