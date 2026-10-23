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
