# 05: 每日汇总同步

**What to build:** `runsync sync` 同时拉取每日汇总（静息心率等），写进原始档案和分析库。每次都重拉最近 7 天，接住当天不完整的数据和 Garmin 事后的修正。

**Blocked by:** 04（Personal API 活动同步）

**Status:** ready-for-agent

来源：[实施 spec](../spec.md)，User Story 15。

- [ ] 每日汇总按 7 天一个区间请求，每天一个 JSON 文件存进原始档案
- [ ] 回填从 2021-08 开始；之后每次同步重拉最近 7 天，覆盖同名文件
- [ ] `daily_wellness` 每天一行，用 upsert 写入；`rebuild` 也能从原始档案重建这张表
- [ ] HRV 和睡眠的空响应只留在原始档案里，不建表
- [ ] Seam 1 测试：同一天重复写入时是 upsert
- [ ] Seam 2 测试：最近 7 天的每日汇总被覆盖，更早的不重拉
