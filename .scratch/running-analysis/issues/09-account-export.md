# 申请 Garmin 账号数据导出

Type: task
Status: open
Blocked by: none

## Question

在 Garmin 账号设置里申请一次完整的账号数据导出（Garmin 处理要几天）。导出包里的原始 FIT 和手表上的文件逐字节一致，可以作为 5 年历史的原始存档兜底；同时用来确认导出包里健康数据（HRV、睡眠、静息心率）的格式。这一点 [Garmin Connect 数据获取途径调研](01-garmin-data-access.md) 没能核实。

需要用户本人操作（HITL）。拿到导出包后在 Answer 里记录：包的存放位置、目录结构、FIT 文件数量和时间范围、健康数据的文件格式。

## Comments

- 2026-10-23（来自 [项目骨架与依赖](11-project-skeleton.md)）：数据目录由环境变量 `RUNNING_DATA_DIR` 指定，默认 `%USERPROFILE%\running-data`。导出包解压到其中的 `raw/export/<导出日期>/`。
- 2026-10-24：不阻塞任何 ticket，也不阻塞地图收尾。用户去 Garmin 网站申请导出，导出包到了之后再记录 Answer 并关闭这个 ticket。
