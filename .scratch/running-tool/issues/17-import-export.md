# 17: 导入 Garmin 账号数据导出包

**What to build:** 新命令 `runsync import-export <zip>`：把 Garmin 账号数据导出包原样存进原始档案，并解析写入分析库，让本机不经 API 就拥有 2021-08 起的历史。之后的 `runsync sync` 只补导出日期之后的新数据，不重复拉取导出包里已有的内容。完全离线。

**Blocked by:** 05（每日汇总同步），06（garminconnect 指标），07（限流冷却与凭据失效处理）

**Status:** done

来源：[实施 spec](../spec.md)，User Stories 9–11、31；本 ticket 修改了 spec「原始档案布局」里"导出包只存档，不解析"这一条。

## 导出包结构（来自用户 2026-10 的真实导出包，只看过结构）

- `DI_CONNECT/DI-Connect-Fitness/<email>_<n>_summarizedActivities.json`：所有活动的摘要（约 1100 个，2021-08 起），字段有 `activityId`、`activityType`、`beginTimestamp`、`startTimeLocal`、`startTimeGmt`、`distance`、`duration`、`avgHr`、`maxHr`、`elevationGain` 等。**单位不是 SI**（例如距离可能是 cm、时长可能是 ms），实施时要用距离/时长/配速互相校验确认。
- `DI_CONNECT/DI-Connect-Uploaded-Files/UploadedFiles_0-_Part{1,2,3}.zip`：zip 里套 zip，共约 17770 个 `.fit`，混有日常监测类 FIT；按 `file_id` 的 `type` 只取 activity，再对应到 `activityId`（文件名或 session 开始时间对 `beginTimestamp`，实施时确认）。
- `DI_CONNECT/DI-Connect-Aggregator/UDSFile_*.json`：每日汇总（静息心率、步数、压力、Body Battery 等）。
- `DI_CONNECT/DI-Connect-Metrics/`：`MetricsMaxMetData_*`（vo2Max）、`RunRacePredictions_*`（5K/10K/半马/全马预测）、`TrainingHistory_*`（训练状态、负荷）。
- 其余（睡眠、个人资料等）只存档，不解析。

## 要求

- [x] `runsync import-export <zip>`：zip 原样复制到 `raw/export/<导出日期>/`（导出日期的取法写进结论），然后从这份存档解析。重复导入同一个包是幂等的；导入更新的包时新数据覆盖旧数据
- [x] 活动摘要写入 `activities`，换算成 SI，时间列遵守 `conventions.md` 的格式；活动类型和 Personal API 的类型键一致（不一致时做映射）
- [x] activity FIT 解析写入 `records`、`laps`，复用现有 FIT 解析；非 activity 的 FIT 跳过；解析失败的 FIT 计数并跳过，不中断
- [x] UDS 每日汇总写入 `daily_wellness`；三项 Garmin 指标写入 `garmin_metrics`，字段对不上的留 NULL
- [x] 同一活动或同一天既有导出数据又有 Personal API / garminconnect 数据时，API 数据优先
- [x] `runsync rebuild` 也从 `raw/export/` 重建上述数据，结果与直接导入一致
- [x] `runsync sync`：导出包里已有的活动算作"已有"（翻页停止、不下载 FIT 和详情，最近 7 天的刷新规则不变）；导出包已覆盖的日子不再回填每日汇总；garminconnect 回填同理
- [x] 命令结束时输出汇总：各类条目数、跳过的非 activity FIT 数、解析失败数、数据日期范围。不输出 GPS 坐标
- [x] Seam 1 测试：手写的迷你导出包 fixture（合成 JSON + 合成小 FIT，不含真实 GPS、不含邮箱），断言各表行数、单位、幂等、API 优先、rebuild 一致
- [x] Seam 2 测试：导入后 `sync` 对导出包已有的活动和日子不再请求
- [x] 读真实导出包的集成测试标 `#[ignore]`，从数据目录读
- [x] README 写明导入步骤

## 安全

- 真实导出包含 GPS 和邮箱，不进 git（仓库 `.gitignore` 已有 `*.zip`）。fixture 全部手写合成。
- 用真实包手动验证时，只用临时 `RUNNING_DATA_DIR`（放在仓库外），只看汇总数字，验证完删除临时目录。不碰 `%USERPROFILE%\running-data`。
- 导出包是不可信数据：解析时防 zip 路径穿越（不按条目名写文件），不在解压目录里运行任何东西。

## 结论

实现在 `importer/src/export.rs`（`runsync::export`），以下都用 2026-10 的真实包核对过（只看汇总数字）。

- **导出日期**：包内所有条目修改时间里最新的那天。真实包所有条目都是 2026-10-30，所以存到 `raw/export/2026-10-30/<原文件名>`。包从不解压到磁盘：条目只读进内存、按名字挑选，嵌套的 `UploadedFiles_*.zip` 也在内存里打开；单个条目超过 1 GiB 不读。
- **活动单位**（用 FIT session 的距离、时长、热量交叉核对）：`beginTimestamp` 是 UTC 毫秒；`startTimeLocal` 是把本地钟面时间当 UTC 写成的毫秒数；`duration`/`movingDuration`/`elapsedDuration` 是 ms；`distance`、`elevationGain/Loss` 是 cm；`avgSpeed`/`maxSpeed` 乘 10 才是 m/s；`calories` 除以 4.19 才是 kcal。`activityType` 的值（`running`、`track_running`、`walking` 等）与 Personal API 的类型键相同，不需要映射。`timeZoneId` 只有 Garmin 内部的数字 id，所以 `time_zone` 留 NULL。
- **FIT 对应活动**：FIT 里没有 activityId，按 session 开始时间（Unix 秒）== `beginTimestamp / 1000` 对应（真实包 1097 个 activity FIT 中 1096 个对上）。`file_id.type` 不是 activity 的 FIT 计为"not an activity"跳过；对不上任何活动的计为"matching no activity"；解析失败的计数后跳过。
- **Garmin 指标**：`MetricsMaxMetData` 只取 `sport == RUNNING` 的行（`vo2MaxValue`）；`RunRacePredictions` 写四个比赛预测；`TrainingHistory` 只有训练状态，没有 acute/chronic 负荷，这几列留 NULL。同一天多行时取更新时间最新的一行。训练状态的词表与 API 不同：导出包写 `PRODUCTIVE`，API 写 `PRODUCTIVE_1`；后来（2026-10-31，见 18）API 的数字后缀在写入时去掉，两边统一存 `PRODUCTIVE`。
- **优先级**：API 已存档的数据（`raw/personal_api/activities/<id>.json|.fit`、非 `null` 的 `raw/personal_api/daily_summaries/<日期>.json`、`raw/garminconnect/<metric>/<日期>.json`）优先，导出包里对应的那份直接不加载，所以与加载顺序无关。多个导出包按导出日期从旧到新加载；导入一个包后，导出日期不早于它的已存档包会重新加载一遍，保证新包覆盖旧包。重复导入同一个包是幂等的。`rebuild` 在 API 文件之后加载 `raw/export/` 下所有包，结果与直接导入一致（Seam 1 测试逐行比对 `activities`、`records`、`laps`、`daily_wellness`、`garmin_metrics`）；单个包加载失败时 `rebuild` 回滚这个包并继续。
- **sync 的处理**：`activities` 表里已有的活动（不管来自 API 还是导出包）算"已有"：翻页照常停止，不下载详情和 FIT；最近 7 天的刷新不变。新增 migration `0006_export_packages.sql`，表 `export_packages` 记每个包的导出日期和每日汇总/指标各自的第一天；`db::export_covers` 判断某天是否落在某个包"第一天..导出日期"之间。每日汇总回填把这些日子视作已存档；garminconnect 回填跳过这些日子。今天的快照和最近 7 天照常请求。
- **真实包结果**（临时数据目录，耗时约 66 s，验证完已删除）：活动 1098 个；FIT 共 17770 个，其中 1096 个 activity FIT 载入，1 个对不上活动，16673 个非 activity 跳过，0 个解析失败；每日汇总 1912 天（2021-08-06..2026-10-30）；Garmin 指标 1909 天（2021-08-07..2026-10-30）。之后的 `runsync rebuild` 也成功重建。
