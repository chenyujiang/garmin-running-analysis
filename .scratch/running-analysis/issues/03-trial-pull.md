# 试拉一小批真实数据

Type: task
Status: resolved
Blocked by: 01

## Question

按 [Garmin Connect 数据获取途径调研](01-garmin-data-access.md) 的结论，拉取少量真实数据，看清数据的真实形态，以便决定存储方案：

- **Personal API**：最近约 10 次跑步活动的汇总 + FIT，以及几天的 HRV、静息心率、睡眠。顺便测一下能往回查多早的数据。
- **`garminconnect`**：只登录一次，拉 Training Status、VO2max、Race Predictor 各一次，串行慢速。
- **FIT 对比**：同一次活动，把 Personal API 下载的 FIT 和 `garminconnect` 的 `ORIGINAL` FIT（或手表上的原文件）对比，确认私有字段有没有丢。

需要用户本人创建 API key、输入密码登录（HITL）。完成后在 Answer 里记录：API key / token 存放位置、实际拿到的字段和文件格式、能回溯的最早日期、单次请求耗时、有没有遇到限流、FIT 对比结果。

## Comments

- 2026-10-23：用户已在 Garmin Connect 创建 Personal API key，存于仓库根目录 `.env`（已被 `.gitignore` 排除）。
- 2026-10-23：旧 key 在本 session 中被误打印到对话里，用户已作废并换了新 key，有效期 1 年。`.env` 里是一行裸 key，没有 `KEY=` 前缀。

## Answer

2026-10-23 完成。脚本在 `.scratch/running-analysis/trial/`，拉下来的原始数据在 `trial/data/`（已被 gitignore 排除）。

**凭据**
- Personal API key：仓库根目录 `.env`，一行裸 key，有效期 1 年（到 2027-10）。官方客户端把 access token 缓存在 `~/.config/garmin/connect-personal-api-bearer-token.json`，有效期 24 小时。
- `garminconnect` token：`~/.garminconnect`。库会把这个目录的权限收紧，Git Bash 读不了。密码没有落盘。

**Personal API**（官方客户端 `garmin-connect-personal-api-python`，请求之间停 1.5 秒）
- 共约 200 次请求，没有遇到 429。换 token 约 1.8 秒，其他请求 0.2–0.6 秒。
- `search_activities`：返回 list of dict，约 80 个字段（`activityId`、`activityType.typeKey`、`startTimeLocal`、`distance`、`duration`、`averageHR`、`averageSpeed`、`elevationGain`、`hrTimeInZone_1..5`、`splitSummaries` 等）。可以用 `start` 翻页；offset 1000 时还有数据，1500 时为空，所以活动总数在 1000–1500 之间。
- `get_activity`：返回 `summaryDTO`、`splitSummaries`、`metadataDTO` 等，约 3–5KB。
- `download_activity`：返回 zip，里面只有一个 `<id>_ACTIVITY.fit`（约 94KB，30 分钟左右的跑步约 1800 条 `record`）。
- **最早的活动是 2021-08-06**，再早没有数据。2021 年的活动类型有 running、walking、strength_training、assistance。
- 每日汇总 `get_daily_summaries` 返回 `{data: [...]}`，最早从 2021-10 左右开始有。静息心率在 `heartRate.restingValue`，有些天为空。
- HRV 和睡眠：最近 30 天全部为空（HRV 返回 `None`，睡眠返回空字段的 dict，`sleep_summaries` 返回 `[]`）。原因是用户晚上不戴手表，不是 API 的问题。
- `get_heart_rate_zones` 会返回 Garmin 当前在用的 HRmax、LTHR、静息心率设定，可以作为参照值。

**garminconnect 0.3.19**（请求之间停 5 秒）
- 登录：`mobile+cffi` 和 `mobile+requests` 两个策略都返回 429，库自动退到后面的策略后登录成功，总耗时 11.8 秒。说明 mobile 策略在本机或本 IP 已被拦截，以后要尽量复用 token，少走登录。
- `get_training_status`、`get_max_metrics`、`get_race_predictions` 都正常返回。VO2max 有 `vo2MaxPreciseValue`；Race Predictor 返回 5K、10K、半马、全马用时（秒）；Training Status 返回 `weeklyTrainingLoad`、`loadTunnelMin/Max`、`trainingStatus`。

**FIT 对比**
- 抽了 3 次活动：Personal API 下载的 FIT 和 `garminconnect` `ORIGINAL` 下载的 FIT **逐字节一致**。两个 zip 只在头部第 11 字节（文件修改时间）有差别。
- FIT 里保留了 Garmin 的私有消息（`unknown_233`、`unknown_325`、`unknown_104`、`unknown_140` 等），没有开发者字段。
- 结论：Personal API 下载的 FIT 就是原始文件，不需要再用 `garminconnect` 下载 FIT。
