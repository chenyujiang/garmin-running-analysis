# 回填与增量同步策略

Type: grilling
Status: open
Blocked by: 01, 03, 10

## Question

5 年历史怎么回填、之后怎么增量同步？同步逻辑由 Rust 导入 CLI 实现。

- 回填节奏：限速多少、分几批、中断后如何续传。
- 增量触发：手动跑命令，还是 Windows 任务计划程序定时跑。
- 怎么判断"新数据"：按活动 ID、按日期，健康数据（HRV、睡眠）事后被 Garmin 修正时怎么处理。
- token 过期或接口失效时的行为和后备（手动导出）。
- Training Status / VO2max / Race Predictor 由 Rust CLI 调一个 Python 小脚本获取（见 [Rust 导入 CLI 如何调用 Garmin 接口](10-rust-api-coverage.md)）。这个脚本的登录状态和 Personal API 的 token 缓存是分开的，要分别处理过期和 429 的情况。

## Comments

- 2026-10-23（来自 [存储方案](04-storage.md)）：要拉取所有活动类型，不只是跑步。Garmin 事后修正的某天数据，重新拉取后覆盖原始档案里对应日期的文件。导入 CLI 需要一个"从原始档案重建分析库"的命令，什么时候触发它在这里决定。增量同步时 Jupyter 或仪表盘可能正在读取分析库，SQLite 的 WAL 模式允许这种情况。
