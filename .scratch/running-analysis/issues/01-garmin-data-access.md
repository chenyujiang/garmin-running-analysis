# Garmin Connect 数据获取途径调研

Type: research
Status: resolved
Blocked by: none

## Question

截至 2026 年，从 Garmin Connect 国际版（未开 MFA）以个人身份拉取自己数据，最可行的途径是什么？

具体要查清：

- `garminconnect` / `garth` 等非官方库现在还在维护、还能用吗？登录流程、token 持久化位置和有效期。
- 能拿到哪些数据：活动列表、原始 FIT 文件下载（逐秒数据流）、HRV、静息心率、睡眠，以及 Garmin 自带的 Training Load、VO2max、Race Predictor。
- 限流和锁号的已知行为：回填 5 年历史需要多慢才安全。
- 后备途径：账号数据导出（Garmin 的数据导出请求）里包含什么、什么格式，能否覆盖上面的数据。

## Answer

详细调研（每条附来源）：分支 `research/garmin-data-access` 的 `research/garmin-data-access.md`（commit `031a024`，仅本地）。

- **主力途径：官方 Garmin Connect Personal API**（2026-10-21 发布，官方 Python 客户端 `garmin/connect-personal-api-python` v1.0.0）。只读；API key（有效期 30 天至 1 年）换 24 小时 access token，无 refresh token。覆盖活动列表/详情、FIT 下载（zip）、HRV、睡眠、每日汇总（含 `restingHeartRate`）。**不含** Training Status、VO2max 趋势、Race Predictor。
- **`garth` 已弃用**（2026-03-28），因 Garmin 改了登录流程，自 2026-03-17 起新登录被 Cloudflare 429。
- **`garminconnect` 仍维护**（0.3.19，2026-10-16）。用于补 `get_training_status`、`get_max_metrics_range`、`get_race_predictions`。token 存在 `~/.garminconnect/garmin_tokens.json`。原始 FIT 要传 `ActivityDownloadFormat.ORIGINAL`。库本身不限速；已知 429 多发生在登录环节，有一例锁号 48-72 小时以上。用法：只登录一次，串行慢速，遇到 429/403 立即停。
- **账号数据导出**：里面的 FIT 与手表上的文件逐字节一致，作为 5 年原始存档兜底。导出包里健康数据的格式未能核实。
- **未决风险**：Personal API 能往回查多久、限流多少都没有公开；经 API 下载的 FIT 可能被改写，丢失私有字段（待实测）；非官方登录随时可能再失效。
