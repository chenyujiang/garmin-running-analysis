# 试拉一小批真实数据

Type: task
Status: open
Blocked by: 01

## Question

按 [Garmin Connect 数据获取途径调研](01-garmin-data-access.md) 的结论，拉取少量真实数据，看清数据的真实形态，以便决定存储方案：

- **Personal API**：最近约 10 次跑步活动的汇总 + FIT，以及几天的 HRV、静息心率、睡眠。顺便测一下能往回查多早的数据。
- **`garminconnect`**：只登录一次，拉 Training Status、VO2max、Race Predictor 各一次，串行慢速。
- **FIT 对比**：同一次活动，把 Personal API 下载的 FIT 和 `garminconnect` 的 `ORIGINAL` FIT（或手表上的原文件）对比，确认私有字段有没有丢。

需要用户本人创建 API key、输入密码登录（HITL）。完成后在 Answer 里记录：API key / token 存放位置、实际拿到的字段和文件格式、能回溯的最早日期、单次请求耗时、有没有遇到限流、FIT 对比结果。

## Comments

- 2026-10-23：用户已在 Garmin Connect 创建 Personal API key，存于仓库根目录 `.env`（已被 `.gitignore` 排除）。有效期待记录。
