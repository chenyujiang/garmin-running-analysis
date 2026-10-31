# 08: 第一次全量回填

**What to build:** 用真实数据完成第一次全量回填，让本机拥有 2021-08 起的全部历史，并确认导入 CLI 在真实数据上可用。历史部分来自账号数据导出包（`runsync import-export`，离线），导出日期之后的新数据由 `runsync sync` 补齐。这是 HITL ticket：命令由用户手动运行。

**Blocked by:** 05（每日汇总同步），07（限流冷却与凭据失效处理），17（导入 Garmin 账号数据导出包）

**Status:** done

来源：[实施 spec](../spec.md)，User Stories 9–11；Out of Scope 里的"数据质量与清洗"和"温度校正"。

- [x] 运行 `runsync import-export <zip>`（包已复制进 `raw/export/`；仓库根目录的原件被 `*.zip` 忽略，用户可自行删除）
- [x] 用户再运行 `runsync sync`，补导出日期之后的新数据（中断后再次运行即可续传）
- [x] agent 只核对汇总信息：各表行数、活动日期范围、各活动类型的数量、跳过的非 activity FIT 数量、解析失败的 FIT 数量；不读取、不输出 GPS 坐标
- [x] 如果遇到 429，按冷却规则处理，不重试
- [x] 解析失败的 FIT 比例偏高时，评估是否换 `rustyfit`，结论记在本 ticket
- [x] 回填完成后，在 `.scratch/running-tool/issues/` 新开两个 ticket："数据质量与清洗"和"温度校正"
- [x] 确认 `raw/`（包括 `raw/export/`）已纳入用户的备份（用户 2026-10-31 确认）

## 结论

- **import-export**（2026-10-31，经用户授权由 agent 运行）：包存到 `raw/export/2026-10-30/`。活动 1098 个；FIT 17770 个，其中 1096 个 activity FIT 载入，1 个对不上活动，16673 个非 activity 跳过，**0 个解析失败**，不需要换 `rustyfit`。每日汇总 1912 天（2021-08-06..2026-10-30），Garmin 指标 1909 天（2021-08-07..2026-10-30）。
- **sync**（用户运行，2026-10-31）：`sync_runs` 两行，`personal_api` 和 `garminconnect` 都是 `ok`，共约 30 s，没有 429，没有冷却标记。新增 1 个活动（2026-10-31），每日汇总和 Garmin 指标补到 2026-10-31。导出包已覆盖的日子没有重新请求。
- **最终行数**：`activities` 1099（running 1073、track_running 17、indoor_cardio 4、walking 2、strength_training 2、assistance 1），`records` 3363903，`laps` 11617，`daily_wellness` 1913，`garmin_metrics` 1910。活动日期 2021-08-06..2026-10-31。2 个活动没有逐秒记录（记入 18）。
- **`config.toml`**：用户确认 `hr_max = 193`、`hr_rest = 55`、`lthr = 170`，`effective_from = 2021-08-01`。依据：单次最大心率在 2022、2025 两天到 193；Garmin 的静息心率不可用（只在白天戴表），改取每日最低心率的 10 分位；LTHR 取导出包里的 Garmin 设置，与 10K、半马平均心率一致。
- 新开 [18 数据质量与清洗](18-data-quality.md)、[19 温度校正](19-temperature-correction.md)。
