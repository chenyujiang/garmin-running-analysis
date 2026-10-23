# 03: FIT 解析进 `records` 和 `laps`

**What to build:** `runsync rebuild` 解析原始档案里的 FIT 文件，把逐秒数据流和分段写进分析库，让后面的分析有数据可用。一个文件解析失败只会被记录和跳过，不会中断整次重建。

**Blocked by:** 02（Tracer bullet：从原始档案到仪表盘空状态）

**Status:** ready-for-agent

来源：[实施 spec](../spec.md)，User Story 30；Implementation Decisions 里的"FIT 解析"和"分析库 schema"。

- [ ] 用 `fitparser` 解析 FIT；先确认它在 Windows 上能构建，不行就换 `rustyfit`，并在本 ticket 记下原因
- [ ] `records` 表主键为 `(activity_id, timestamp)`，列有 `heart_rate`、`speed`、`cadence`、`altitude`、`distance`、`lat`、`lon`、`power`、`temperature`，缺失为 NULL；单位 SI，时间戳 UTC；`cadence` 按 FIT 原样存单脚步频
- [ ] `laps` 表存手表的分段
- [ ] 私有消息（`unknown_*`）不入库
- [ ] 无法解析的 FIT（包括 `fitparser` issue #58 那类）留在原始档案里，记一条日志，然后跳过
- [ ] Seam 1 测试：fixture 里放几个合成的小 FIT（不含真实 GPS），外加一个坏文件；断言 `records` 和 `laps` 的行数和单位，并断言坏文件被跳过而不是中断
- [ ] 读取真实 FIT 的集成测试从数据目录读文件，标 `#[ignore]`，用 `cargo test -- --ignored` 手动运行
