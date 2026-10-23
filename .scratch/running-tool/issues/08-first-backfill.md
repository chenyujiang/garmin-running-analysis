# 08: 第一次全量回填

**What to build:** 用真实账号跑一次完整回填，让本机第一次拥有 2021-08 起的全部历史，并确认导入 CLI 在真实数据上可用。这是 HITL ticket：由用户手动运行 `runsync sync`，耗时约 75 分钟。

**Blocked by:** 05（每日汇总同步），07（限流冷却与凭据失效处理）

**Status:** ready-for-agent

来源：[实施 spec](../spec.md)，User Stories 9–11；Out of Scope 里的"数据质量与清洗"和"温度校正"。

- [ ] 用户手动运行 `runsync sync`，直到回填完成（中断后再次运行即可续传）
- [ ] agent 只核对汇总信息：各表行数、活动日期范围、各活动类型的数量、解析失败的 FIT 数量；不读取、不输出 GPS 坐标
- [ ] 如果遇到 429，按冷却规则处理，不重试
- [ ] 解析失败的 FIT 比例偏高时，评估是否换 `rustyfit`，结论记在本 ticket
- [ ] 回填完成后，在 `.scratch/running-tool/issues/` 新开两个 ticket："数据质量与清洗"和"温度校正"
- [ ] 确认 `raw/` 已纳入用户的备份
