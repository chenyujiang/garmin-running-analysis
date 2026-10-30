# 08: 第一次全量回填

**What to build:** 用真实数据完成第一次全量回填，让本机拥有 2021-08 起的全部历史，并确认导入 CLI 在真实数据上可用。历史部分来自账号数据导出包（`runsync import-export`，离线），导出日期之后的新数据由 `runsync sync` 补齐。这是 HITL ticket：命令由用户手动运行。

**Blocked by:** 05（每日汇总同步），07（限流冷却与凭据失效处理），17（导入 Garmin 账号数据导出包）

**Status:** ready-for-agent

来源：[实施 spec](../spec.md)，User Stories 9–11；Out of Scope 里的"数据质量与清洗"和"温度校正"。

- [ ] 用户把导出包从仓库根目录移出，运行 `runsync import-export <zip>`
- [ ] 用户再运行 `runsync sync`，补导出日期之后的新数据（中断后再次运行即可续传）
- [ ] agent 只核对汇总信息：各表行数、活动日期范围、各活动类型的数量、跳过的非 activity FIT 数量、解析失败的 FIT 数量；不读取、不输出 GPS 坐标
- [ ] 如果遇到 429，按冷却规则处理，不重试
- [ ] 解析失败的 FIT 比例偏高时，评估是否换 `rustyfit`，结论记在本 ticket
- [ ] 回填完成后，在 `.scratch/running-tool/issues/` 新开两个 ticket："数据质量与清洗"和"温度校正"
- [ ] 确认 `raw/`（包括 `raw/export/`）已纳入用户的备份
