# 20: 导入侧的数据清洗

**What to build:** 按 18 确认的结论改导入代码：FIT 与活动的匹配允许小的时间差，导出包活动补上 `time_zone`，不再导入不可用的 Garmin 静息心率。

**Blocked by:** 18（数据质量与清洗）

**Category:** enhancement

**Status:** needs-triage

来源：[18 数据质量与清洗](18-data-quality.md) 的结论，用户 2026-10-31 确认的第 1、5、6 条建议。

## 要求

- [ ] **FIT 匹配容差**：导出包的 activity FIT 先按 session 开始时间 == `beginTimestamp` 精确匹配；失败时，匹配到开始时间相差 ±120 s 以内、唯一最近的活动。有两个以上候选时不匹配，仍计入"matching no activity"。活动汇总（距离等）保持 Garmin 的值，FIT 只提供 `records` 和 `laps`。
  - 真实数据里这会让 `9136530487`（2022-07-04，FIT 开始时间晚 50 s）有逐秒记录。
- [ ] **`time_zone`**：导出包活动按 `start_time_local − start_time_utc` 的偏移推出时区：
  - 偏移等于 `Pacific/Auckland` 在那个时刻的偏移时，写 `Pacific/Auckland`；
  - 其余写固定偏移，格式 `+08:00`，不猜城市。
  - API 来的活动不变。`conventions.md` 说明 `time_zone` 可能是 IANA 名字，也可能是固定偏移。
- [ ] **`resting_hr_bpm`**：导出包和 Personal API 的每日汇总都不再导入这一列，写 NULL。原始档案保持原样。`conventions.md`（或 schema 注释）说明原因：用户只在白天戴表，Garmin 的静息心率偏高，不可用；静息心率用 `config.toml` 的 `hr_rest`。
- [ ] `runsync rebuild` 的结果与重新导入一致；Seam 1 测试覆盖上面三条（合成 fixture，不含真实 GPS 和邮箱）。
- [ ] 用户在真实数据目录运行 `runsync rebuild` 后，agent 只读核对：`9136530487` 有逐秒记录，`time_zone` 为 NULL 的活动数为 0，`resting_hr_bpm` 全部为 NULL。

## 不做

- `8234857240`（导出包和 API 档案里都没有 FIT）：忽略，不补下载。
- 修改 Garmin 的活动汇总值。
