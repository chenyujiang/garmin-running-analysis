# 17: 导入 Garmin 账号数据导出包

**What to build:** 新命令 `runsync import-export <zip>`：把 Garmin 账号数据导出包原样存进原始档案，并解析写入分析库，让本机不经 API 就拥有 2021-08 起的历史。之后的 `runsync sync` 只补导出日期之后的新数据，不重复拉取导出包里已有的内容。完全离线。

**Blocked by:** 05（每日汇总同步），06（garminconnect 指标），07（限流冷却与凭据失效处理）

**Status:** ready-for-agent

来源：[实施 spec](../spec.md)，User Stories 9–11、31；本 ticket 修改了 spec「原始档案布局」里"导出包只存档，不解析"这一条。

## 导出包结构（来自用户 2026-10 的真实导出包，只看过结构）

- `DI_CONNECT/DI-Connect-Fitness/<email>_<n>_summarizedActivities.json`：所有活动的摘要（约 1100 个，2021-08 起），字段有 `activityId`、`activityType`、`beginTimestamp`、`startTimeLocal`、`startTimeGmt`、`distance`、`duration`、`avgHr`、`maxHr`、`elevationGain` 等。**单位不是 SI**（例如距离可能是 cm、时长可能是 ms），实施时要用距离/时长/配速互相校验确认。
- `DI_CONNECT/DI-Connect-Uploaded-Files/UploadedFiles_0-_Part{1,2,3}.zip`：zip 里套 zip，共约 17770 个 `.fit`，混有日常监测类 FIT；按 `file_id` 的 `type` 只取 activity，再对应到 `activityId`（文件名或 session 开始时间对 `beginTimestamp`，实施时确认）。
- `DI_CONNECT/DI-Connect-Aggregator/UDSFile_*.json`：每日汇总（静息心率、步数、压力、Body Battery 等）。
- `DI_CONNECT/DI-Connect-Metrics/`：`MetricsMaxMetData_*`（vo2Max）、`RunRacePredictions_*`（5K/10K/半马/全马预测）、`TrainingHistory_*`（训练状态、负荷）。
- 其余（睡眠、个人资料等）只存档，不解析。

## 要求

- [ ] `runsync import-export <zip>`：zip 原样复制到 `raw/export/<导出日期>/`（导出日期的取法写进结论），然后从这份存档解析。重复导入同一个包是幂等的；导入更新的包时新数据覆盖旧数据
- [ ] 活动摘要写入 `activities`，换算成 SI，时间列遵守 `conventions.md` 的格式；活动类型和 Personal API 的类型键一致（不一致时做映射）
- [ ] activity FIT 解析写入 `records`、`laps`，复用现有 FIT 解析；非 activity 的 FIT 跳过；解析失败的 FIT 计数并跳过，不中断
- [ ] UDS 每日汇总写入 `daily_wellness`；三项 Garmin 指标写入 `garmin_metrics`，字段对不上的留 NULL
- [ ] 同一活动或同一天既有导出数据又有 Personal API / garminconnect 数据时，API 数据优先
- [ ] `runsync rebuild` 也从 `raw/export/` 重建上述数据，结果与直接导入一致
- [ ] `runsync sync`：导出包里已有的活动算作"已有"（翻页停止、不下载 FIT 和详情，最近 7 天的刷新规则不变）；导出包已覆盖的日子不再回填每日汇总；garminconnect 回填同理
- [ ] 命令结束时输出汇总：各类条目数、跳过的非 activity FIT 数、解析失败数、数据日期范围。不输出 GPS 坐标
- [ ] Seam 1 测试：手写的迷你导出包 fixture（合成 JSON + 合成小 FIT，不含真实 GPS、不含邮箱），断言各表行数、单位、幂等、API 优先、rebuild 一致
- [ ] Seam 2 测试：导入后 `sync` 对导出包已有的活动和日子不再请求
- [ ] 读真实导出包的集成测试标 `#[ignore]`，从数据目录读
- [ ] README 写明导入步骤

## 安全

- 真实导出包含 GPS 和邮箱，不进 git（仓库 `.gitignore` 已有 `*.zip`）。fixture 全部手写合成。
- 用真实包手动验证时，只用临时 `RUNNING_DATA_DIR`（放在仓库外），只看汇总数字，验证完删除临时目录。不碰 `%USERPROFILE%\running-data`。
- 导出包是不可信数据：解析时防 zip 路径穿越（不按条目名写文件），不在解压目录里运行任何东西。
