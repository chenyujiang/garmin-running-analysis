# 03: FIT 解析进 `records` 和 `laps`

**What to build:** `runsync rebuild` 解析原始档案里的 FIT 文件，把逐秒数据流和分段写进分析库，让后面的分析有数据可用。一个文件解析失败只会被记录和跳过，不会中断整次重建。

**Blocked by:** 02（Tracer bullet：从原始档案到仪表盘空状态）

**Status:** done

来源：[实施 spec](../spec.md)，User Story 30；Implementation Decisions 里的"FIT 解析"和"分析库 schema"。

- [x] 用 `fitparser` 解析 FIT；先确认它在 Windows 上能构建，不行就换 `rustyfit`，并在本 ticket 记下原因
- [x] `records` 表主键为 `(activity_id, timestamp)`，列有 `heart_rate`、`speed`、`cadence`、`altitude`、`distance`、`lat`、`lon`、`power`、`temperature`，缺失为 NULL；单位 SI，时间戳 UTC；`cadence` 按 FIT 原样存单脚步频
- [x] `laps` 表存手表的分段
- [x] 私有消息（`unknown_*`）不入库
- [x] 无法解析的 FIT（包括 `fitparser` issue #58 那类）留在原始档案里，记一条日志，然后跳过
- [x] Seam 1 测试：fixture 里放几个合成的小 FIT（不含真实 GPS），外加一个坏文件；断言 `records` 和 `laps` 的行数和单位，并断言坏文件被跳过而不是中断
- [x] 读取真实 FIT 的集成测试从数据目录读文件，标 `#[ignore]`，用 `cargo test -- --ignored` 手动运行

## 结论

- **解析库**：`fitparser` 0.11.0 在 Windows（`x86_64-pc-windows-msvc`，rustup stable）上直接构建通过，没有换 `rustyfit`。
- **issue #58**：在 0.11.0 上仍然存在。测试用的合成文件（定义消息里声明了开发者字段，但前面没有 `developer_data_id`/`field_description`）会让整个文件解析失败，于是按"记日志、跳过"处理。
- **schema**：迁移 `0003_records_laps.sql`。
  - `records`：`timestamp` 是带 `Z` 的 ISO UTC；`lat`/`lon` 从 semicircles 换成度；`speed`、`altitude` 优先取 `enhanced_*`，没有时用普通字段；`cadence` 为单脚步频（spm 要乘 2）。没有时间戳的 record 消息丢弃；同一秒重复时后一条覆盖前一条。
  - `laps`：主键 `(activity_id, lap_index)`，`lap_index` 按文件顺序从 0 开始。列：`start_time_utc`、`end_time_utc`、`elapsed_duration_s`、`timer_duration_s`、`distance_m`、`avg_speed_mps`、`max_speed_mps`、`avg_hr_bpm`、`max_hr_bpm`、`avg_cadence`、`max_cadence`（单脚）、`avg_power_w`、`elevation_gain_m`、`elevation_loss_m`。
  - 两张表都没有指向 `activities` 的外键：只有 FIT、没有详情 JSON 的活动也能入库。
- **只读 `record` 和 `lap` 消息**，用 `DropUnknownMessages` 解码，所以私有消息和其他消息都不入库。
- **合成 FIT**：测试时由 `importer/tests/common/fit.rs` 里的小型 FIT 编码器现场生成，仓库里没有二进制 fixture。
- **真实 FIT 测试**：`importer/tests/real_fit.rs`，只解析不重建，不碰真实分析库，只打印计数。实施时数据目录里还没有 FIT 文件（`sync` 尚未实现），所以这条测试还没有对真实数据跑过。
- `rebuild` 输出改为 `rebuilt <path>: N activities, M FIT files, K files skipped`，`skipped` 同时计 JSON 和 FIT。
