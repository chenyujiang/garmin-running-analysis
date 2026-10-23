# Garmin Connect 数据获取途径调研（截至 2026-10-23）

对应 ticket：`.scratch/running-analysis/issues/01-garmin-data-access.md`。
前提：单用户、Garmin Connect 国际版、未开 MFA、Python，要回填约 5 年历史（跑步**活动**含**逐秒数据流**的 FIT、HRV、静息心率、睡眠、Garmin 自带的 Training Load / VO2max / Race Predictor），之后增量同步。

## 结论速览

2026 年有三条路，情况在本月刚发生大变化：

1. **官方 Garmin Connect Personal API**（2026-10-21 发布）：官方、只读、API key 鉴权，覆盖活动列表、活动 FIT 下载、HRV、睡眠、每日汇总（含静息心率），但**不含** Training Status / VO2max 趋势 / Race Predictor 等性能指标端点。
2. **非官方 `garminconnect`（cyberjunky/python-garminconnect）**：仍活跃维护（最新 0.3.19，2026-10-16），覆盖全部所需数据，包括性能指标；但走的是模拟手机 App 的私有登录，2026 年 3 月曾整体失效，目前靠 `curl_cffi` TLS 伪装绕过 Cloudflare。
3. **账号数据导出**（Account Data Management）：作为后备，给出原始 FIT 文件（与手表上的文件逐字节一致），但需人工申请、异步送达，不适合增量同步。

`garth` 已于 2026-03 正式弃用，不要再用。

推荐：**Personal API 为主（活动 + FIT + 健康数据），`garminconnect` 只补 Personal API 没有的性能指标，账号导出做一次性兜底/校验。**详见文末。

---

## 1. `matin/garth`：已弃用

- README 顶部声明：「Garth is deprecated and no longer maintained. Garmin changed their auth flow, breaking the mobile auth approach that Garth depends on.」新登录不能用；已保存的 OAuth1 token 在签发后约 1 年内可能还能用。来源：https://github.com/matin/garth （README）
- 最终版本 `v0.8.0` 发布于 2026-03-28，`import garth` 会触发 `DeprecationWarning`，PyPI 分类改为 `Development Status :: 7 - Inactive`。来源：https://github.com/matin/garth/releases/tag/v0.8.0
- 作者公告（2026-03-27）说明原因是 Garmin 改了鉴权流程，引用 garth #217 与 garminconnect #332。来源：https://github.com/matin/garth/discussions/222
- 触发事件：自 2026-03-17/18 起，`sso.garmin.com/mobile/api/login` 对所有新登录返回 Cloudflare `429 Too Many Requests`，连无鉴权的 `curl -I` 也是 429；已有 token 的 `resume()` 不受影响。来源：https://github.com/matin/garth/issues/217
- 同期 `garminconnect` 用户报告登录 401（`oauth-service/oauth/preauthorized`）。来源：https://github.com/cyberjunky/python-garminconnect/issues/332

## 2. `cyberjunky/python-garminconnect`（PyPI: `garminconnect`）

### 2.1 维护状态

- 仓库未归档，最近 push 2026-10-16；最近版本：`0.3.19`（2026-10-16）、`0.3.18`（2026-10-15）、`0.3.17`（2026-09-29），8 月以来几乎每 1-2 周一版。来源：https://github.com/cyberjunky/python-garminconnect/releases
- `0.3.0`（2026-04-02）用自研鉴权替换 `garth`：走官方 App 同款 mobile SSO，用 `curl_cffi` 做多种 TLS 指纹伪装（Safari/Chrome/Edge）以绕过 Cloudflare 对程序化登录的拦截；旧 token 不兼容，需重新登录。来源：https://github.com/cyberjunky/python-garminconnect/releases/tag/0.3.0
- 要求 Python 3.12+，安装：`pip install --upgrade garminconnect curl_cffi`。来源：https://github.com/cyberjunky/python-garminconnect （README「Installation」）
- `0.3.19` 对照 Garmin Connect 网页端的全部调用补齐了端点（README 称 348 个 public 方法），并把“今天”改为跟随 Garmin 个人资料时区；Windows 上新增 `tzdata` 依赖。来源：https://github.com/cyberjunky/python-garminconnect/releases/tag/0.3.19

### 2.2 登录流程、token 位置与有效期

- 首次登录：`sso.garmin.com/mobile/api/login`，使用 iOS App 的 client ID `GCM_IOS_DARK`；如需 MFA 则回调 `prompt_mfa`（本项目未开 MFA，不涉及）。随后用 service ticket 在 `diauth.garmin.com` 换取 DI OAuth Bearer token（`access_token` + `refresh_token`）。来源：https://github.com/cyberjunky/python-garminconnect （README「Authentication」）
- token 存储：`~/.garminconnect/garmin_tokens.json`（文件 0600，目录 0700），用 `Garmin().login("~/.garminconnect")` 复用。README 提醒 refresh token 等同持久账号访问权，应像密码一样保护。来源：同上
- 有效期：每次请求前自动检查并刷新 access token；「DI tokens auto-refresh indefinitely as long as the refresh token remains valid」，只有 refresh token 过期或被吊销才需重新用账号密码登录。README **未给出** refresh token 的具体寿命。来源：同上
- `login()` 依次尝试多种策略（mobile、SSO widget、web portal，各自带/不带 TLS 伪装），并用一次 API 调用验证 token 真的可用；缓存 token 被拒时会自动丢弃并重新登录。来源：同上；相关 issue https://github.com/cyberjunky/python-garminconnect/issues/369
- 已知坑：API 会话若用纯 `requests` 会被 Cloudflare 403，`curl_cffi` 可用（已修）。来源：https://github.com/cyberjunky/python-garminconnect/issues/444 ；`0.3.18` 起登录后 403 会提示“可能是 Garmin 在拦截你的客户端或网络”。来源：https://github.com/cyberjunky/python-garminconnect/releases/tag/0.3.18

### 2.3 数据覆盖（方法名均出自 README 方法表）

来源：https://github.com/cyberjunky/python-garminconnect （README「API Methods」）；`ActivityDownloadFormat.ORIGINAL` 见 https://github.com/cyberjunky/python-garminconnect/blob/master/demo.py

| 需求 | 方法 |
| --- | --- |
| 活动列表 | `get_activities(start, limit, activitytype)`、`get_activities_by_date(startdate, enddate, activitytype)`、`count_activities()`、`search_activities()` |
| 原始 FIT | `download_activity(activity_id, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)`，返回 zip（内含原始上传文件）；也支持 TCX/GPX/KML/CSV |
| 活动明细 | `get_activity()`、`get_activity_details(activity_id, maxchart=2000, ...)`、`get_activity_splits()`、`get_activity_laps()`、`get_activity_hr_in_timezones()` |
| HRV | `get_hrv_data(cdate)`、`get_hrv_data_range(start, end)` |
| 静息心率 | `get_rhr_day(cdate)`、`get_rhr_daily(start, end)`、`get_daily_heart_rate_stats(start, end)` |
| 睡眠 | `get_sleep_data(cdate)`、`get_daily_sleep(cdate)`、`get_sleep_daily(start, end)` |
| Training Load / Status | `get_training_status(cdate)`、`get_daily_training_status(cdate)`、`get_weekly_training_status(start, end)`，另有 `get_training_readiness_range(start, end)` |
| VO2max | `get_max_metrics(cdate)`、`get_max_metrics_range(start, end, aggregation='daily')`、`get_max_metrics_latest()` |
| Race Predictor | `get_race_predictions(startdate, enddate, _type)` |
| 其他 | `get_endurance_score()`、`get_hill_score()`、`get_lactate_threshold()`、`get_daily_summaries(start, end)` |

注：README 写的是 `download_activity` 默认格式 `TCX`，要原始 FIT 必须显式传 `ORIGINAL`。各端点是否在真实账号上验证过，记录在 https://github.com/cyberjunky/python-garminconnect/blob/master/docs/API_ENDPOINTS.md （0.3.19 release notes 引用）。

### 2.4 限流与锁号

- 库本身**没有**主动限速：`Garmin(..., retry_attempts=3, retry_min_wait=1.0, retry_max_wait=10.0)` 只对 5xx/网络错误做指数退避重试，「401, 429 and 4xx always fail fast」。DI token 交换遇 429 抛 `GarminConnectTooManyRequestsError`。来源：https://github.com/cyberjunky/python-garminconnect/blob/master/garminconnect/api/base.py 、 https://github.com/cyberjunky/python-garminconnect/blob/master/garminconnect/client/session.py
- 已知 429 报告几乎都集中在**登录**而非数据接口：#337（2026-03，OAuth preauthorized 429）https://github.com/cyberjunky/python-garminconnect/issues/337 ；#344 为绕过登录 429 新增 SSO widget 策略 https://github.com/cyberjunky/python-garminconnect/issues/344 ；#453（2026-10，0.3.17 首个 SSO 请求 429 且无 `Retry-After`）https://github.com/cyberjunky/python-garminconnect/issues/453 ；早年 #127 / #213 也是登录限流。
- Garmin 开发者论坛有用户用 v0.3.1 时所有登录策略 429/403，持续 48-72 小时以上，无 MFA、换 IP 无效，网页和手机 App 正常，无官方回复。来源：https://forums.garmin.com/developer/fit-sdk/f/discussion/435087/persistent-429-on-api-login-account-blocked-for-48-hours/2029273
- 维护者称不知道有账号因使用本库被封禁，但承认 Garmin/Cloudflare 侧变化随时可能导致失效。来源：https://github.com/cyberjunky/python-garminconnect/issues/362
- **没有**任何一手来源给出数据接口的具体配额。回填速度只能保守自定：只登录一次并复用 token；串行请求、每次间隔数秒并加随机抖动；分批多日完成；遇 429/403 立即停止并等待数小时，不要重试登录（登录重试正是触发长时间封锁的已知诱因，见上述 #217、论坛帖）。这是基于上述报告的推断，不是官方数字。

## 3. 官方 Garmin Connect Personal API（2026-10-21 新发布）

### 3.1 是什么

- Garmin 开发者计划新增 Personal 档：个人用自己账号生成 API key，读取自己的数据；包含 Activity Data（JSON & .FIT）、Health Data（JSON）、Women's Health Data（JSON），交付方式「Pull only」。来源：https://developer.garmin.com/gc-developer-program/overview/
- 面向个人，「not intended for commercial applications serving multiple end users」。来源：https://developer.garmin.com/gc-developer-program/personal/personal-faq/
- 发布日期 2026-10-21（DC Rainmaker 报道；生成 key 约 8 秒）。来源：https://www.dcrainmaker.com/2026/10/garmin-connect-api-revamps-connect-developer.html
- Garmin 官方 Python 客户端 `garmin/connect-personal-api-python`（Apache-2.0，v1.0.0 发布于 2026-10-21，PyPI 包 `garmin-connect-personal-api-python`，CLI `gc-personal`，Python 3.12+）。来源：https://github.com/garmin/connect-personal-api-python

### 3.2 鉴权与 token

- 在 Garmin Connect 网页 https://connect.garmin.com/app/settings/personalApiToken 创建 key，接受条款，选有效期；key 只显示一次。来源：https://developer.garmin.com/gc-developer-program/personal/personal-api
- key 有效期可选 30 / 90 / 180 天或 1 年，到期前约一周邮件提醒；可随时删除，删除后其 access token 一并失效。来源：https://developer.garmin.com/gc-developer-program/personal/personal-faq/
- 用 `POST https://personal.connectapi.garmin.com/personalapitoken-service/personal-api/personal-api-key/token`，头 `Authorization: ApiKey <key>` 换 OAuth2 access token；access token 有效 24 小时（或到 key 过期为止），**无 refresh token**，过期就再用 key 换。来源：同上两页
- 官方客户端默认把 key 放 `~/.config/garmin/connect-personal-api-key`（或环境变量 `GARMIN_PERSONAL_API_KEY`），bearer token 缓存在 `~/.config/garmin/connect-personal-api-bearer-token.json`，剩余不足 1 小时自动换新。来源：https://github.com/garmin/connect-personal-api-python （README「Authentication」）、 https://github.com/garmin/connect-personal-api-python/blob/main/src/garmin_personal_api/constants.py
- 不需要账号密码、不经过 SSO/Cloudflare 登录，因此不受 2026-03 那类登录 429 影响（推断）。

### 3.3 数据覆盖

Swagger（OpenAPI 3.0.1，`servers: https://personal.connectapi.garmin.com`）共 26 个路径，全部为 GET。来源：https://developer.garmin.com/gc-developer-program/personal/swagger-docs/ （页面内嵌的 OpenAPI 规范）及官方客户端 README 端点表。

| 需求 | Personal API 端点 | 官方客户端方法 |
| --- | --- | --- |
| 活动列表 | `/activitylist-service/activities/search/activities?start&limit&startDate&endDate&activityType` | `search_activities()` |
| 活动详情 | `/activity-service/activity/{activityId}`（汇总、指标、split 汇总；schema 含 `vO2MaxValue`、`activityTrainingLoad`、`trainingEffect`） | `get_activity()` |
| FIT 下载 | `/download-service/files/activity/{activityId}`，返回 zip；Swagger 描述为「Download an activity file in its original format.」 | `download_activity()` |
| HRV | `/hrv-service/hrv/{calendarDate}`、`/hrv-service/hrv/daily/{fromDate}/{toDate}` | `get_daily_hrv()`、`get_daily_hrv_summaries()` |
| 静息心率 | `/wellness-service/wellness/dailyHeartRate?date=`；`/usersummary-service/v2/dailysummaries` 的 schema 含 `restingHeartRate`、`lastSevenDaysAvgRestingHeartRate` | `get_daily_heart_rate()`、`get_daily_summaries()` |
| 睡眠 | `/sleep-service/sleep/dailySleep?date=`、`/sleep-service/sleep/dailySleepSummariesByDate` | `get_daily_sleep()`、`get_daily_sleep_summaries()` |
| 其他 | Body Battery、压力、步数、SpO2、Fitness Age、心率区间、体重等 | 见 README |
| Training Status / 每日训练负荷 | **无** | — |
| VO2max 趋势（max metrics） | **无**（只有单次活动的 `vO2MaxValue` 字段） | — |
| Race Predictor | **无** | — |

- 印证：garminconnect 维护者在 #476 中说 Personal API「the data is very limited」，网页端新增的端点都不在 Personal 版；另一用户指出 endurance score、hill score、running tolerance 等性能指标不可用。来源：https://github.com/cyberjunky/python-garminconnect/issues/476
- DC Rainmaker 评论区有用户报告 training readiness、training status、VO2max 返回「not found」，且 Personal key 只读。来源：https://www.dcrainmaker.com/2026/10/garmin-connect-api-revamps-connect-developer.html （评论，非正文，可信度较低）

### 3.4 FIT 文件是否“原始”——有矛盾

- Swagger 写的是「original format」（见上）。
- 但 DC Rainmaker 正文称 Garmin 会从 API 提供的 FIT 中「stripping out some data they consider proprietary」，手动上传/导出的文件则保留。来源：https://www.dcrainmaker.com/2026/10/garmin-connect-api-revamps-connect-developer.html
- 一篇对比测试：手表文件、账号导出、网页「Export Original」三者逐字节一致（147,212 字节）；经 Connect API 推送给第三方 App 的文件被重写为 FIT profile 21.217、约一半大小，删掉了未在公开 FIT SDK 中记录的消息/字段，但公开字段的逐秒 record（心率、功率、步频等）、HRV 消息、Connect IQ 开发者字段都保留。来源：https://gssns.io/posts/one-activity-four-fit-files/ 。注意：该测试用的是商业 App（SweatStack）收到的文件，**未确认** Personal API 的 `download-service` 是否同样重写。
- 对本项目的影响：逐秒心率/配速/步频/位置属公开字段，应保留；可能丢失的是 Garmin 私有字段（如手表端实时 VO2max、恢复时间、performance condition 等写在 FIT 私有消息里的数据）。

### 3.5 历史范围与限流

- 官方页面与 FAQ **均未说明**限流配额，也未说明 Personal 档可回溯多久。来源：https://developer.garmin.com/gc-developer-program/personal/personal-api 、 https://developer.garmin.com/gc-developer-program/personal/personal-faq/
- 商业档对比：Starter「Historical data: Not included」，Enterprise「1 month+」。来源：https://developer.garmin.com/gc-developer-program/overview/ 。Personal 档是按日期主动拉取的接口（端点都带日期参数），理论上可查任意日期，但这一点需要实测确认。

## 4. 后备：账号数据导出

- 申请入口：https://www.garmin.com/account/datamanagement/ →「Export Your Data」→「Request Data Export」；邮件发下载链接，通常 48 小时内，最长可达 30 天。来源：https://gadgetbridge.org/basics/topics/garmin/import-garmin-connect/ （Garmin 官方支持页对抓取返回 403，未能直接读取）
- 结构：zip 内 `DI_CONNECT/DI-Connect-Uploaded-Files/` 下还有多层 zip，解开后是活动 FIT；包含账号下所有设备的文件。来源：同上
- 活动文件为上传时的原始格式（FIT/GPX/TCX）。来源：https://forums.garmin.com/apps-software/mobile-apps-web/f/garmin-connect-web/407936/export-data ；与手表文件逐字节一致。来源：https://gssns.io/posts/one-activity-four-fit-files/
- 健康类数据（睡眠、HRV 等）在导出包里以 JSON 形式存在的说法仅见于第三方指南，本次**未能从一手来源核实**具体文件名与字段，也未核实是否含 Training Status / Race Predictor 历史。
- 适用性：一次性、人工、异步，无法做增量同步；适合作为 5 年 FIT 的完整原始备份，以及校验 API 下载的 FIT 是否被重写。

## 5. 推荐方案

按数据类型分工：

1. **Personal API（主力，官方、风险最低）**：活动列表、活动详情、FIT 下载、HRV、静息心率、睡眠，回填和增量都走它。直接用 `requests` 调用或用官方 `garmin-connect-personal-api-python`。key 选 1 年有效期，到期前轮换。
2. **`garminconnect`（补充，只取 Personal API 没有的）**：`get_training_status` / `get_weekly_training_status`（Training Load）、`get_max_metrics_range`（VO2max）、`get_race_predictions`（Race Predictor）。这几类按日期范围查询，5 年回填请求量不大。只登录一次，复用 `~/.garminconnect/garmin_tokens.json`；串行、慢速、遇 429/403 即停。版本要锁定并及时跟进（2026 年鉴权已破坏过一次）。
3. **账号数据导出（兜底）**：先申请一次全量导出，拿到 5 年原始 FIT 存档。若 Personal API 下载的 FIT 被证实经过重写，就以导出包的 FIT 作为历史数据源，API 只负责增量。

实施前建议先做一次小规模实测（各取 1 天/1 个活动）：Personal API 能否拿到 5 年前的数据；`download-service` 返回的 FIT 与导出包同一活动是否一致；有无 429 及响应头。

## 6. 未决风险

- **Personal API 限流配额和历史回溯范围未公开**，需实测；回填可能被限速。
- **Personal API 的 FIT 可能被重写**，丢失 Garmin 私有字段（逐秒公开字段预计保留）；官方 Swagger 与 DC Rainmaker 说法矛盾。
- **性能指标只能靠非官方库**：`garminconnect` 依赖模拟 iOS App 登录与 `curl_cffi` TLS 伪装，Garmin/Cloudflare 再改动就会失效（2026-03 先例）；登录 429 封锁有持续 48-72 小时以上的报告，无官方申诉渠道。
- 官方 API 上线后，Garmin 可能更严厉地打击非官方访问（社区担忧，见 https://github.com/cyberjunky/python-garminconnect/issues/476 ），属推测。
- 使用非官方私有端点技术上与 Garmin 服务条款冲突（见 https://github.com/cyberjunky/python-garminconnect/issues/362 中的讨论），本项目已接受此风险。
- `garminconnect` refresh token 实际寿命未公开；Personal API key 最长 1 年，需定期人工轮换。
- 账号导出中健康数据的格式与覆盖范围未经一手来源核实。
