# 存储方案

Type: grilling
Status: resolved
Blocked by: 01, 03

## Question

拉下来的数据存成什么样？

- 原始 FIT / JSON 是否原样保留（作为可重放的事实来源）。
- 分析用存储选哪个：SQLite、DuckDB、Parquet 文件，还是组合。
- 逐秒数据流和汇总数据、健康数据分别怎么组织。
- 存储格式要能由 Rust 导入 CLI 写入、由 Python 分析读取：两边库的支持程度，以及 schema 由哪一边定义。
- 原始 FIT 字节和 API 原始 JSON 先原样落盘，再解析（见 [Rust 导入 CLI 如何调用 Garmin 接口](10-rust-api-coverage.md)）。解析结果可以随时从原始文件重建。

## Answer

2026-10-23 与用户逐条讨论后确定。数据量很小（约 1000–1500 个活动，原始文件约 150–250MB，逐秒数据约 270 万行），所以选型看的是并发访问和上手难度，不看性能。

**两层结构**（术语见 `GLOSSARY.md`）：**原始档案**是事实来源，**分析库**可以随时删掉，再从原始档案重建。

**数据目录**放在仓库外，例如 `%USERPROFILE%\running-data\`，路径由配置或环境变量指定。这样不会被误提交，也不会在各个 worktree 里各存一份。

**原始档案**（`raw/`）：

```
raw/
  personal_api/activities/<activityId>.fit        # 从 zip 解出，zip 丢弃（zip 里只有 FIT 和修改时间）
  personal_api/activities/<activityId>.json       # get_activity 详情
  personal_api/daily_summaries/<YYYY-MM-DD>.json  # 每天一个文件
  garminconnect/<metric>/<YYYY-MM-DD>.json        # Training Status / VO2max / Race Predictor 每日快照
  export/<导出日期>/                               # 账号数据导出包原样解压，只存档，不解析
```

- 所有活动类型都拉取并入库，不只是跑步，分析时再按类型筛选。这样以后决定把非跑步活动算进负荷时，不需要重新回填。
- Garmin 事后修正某天的数据时，重新拉取后覆盖那一天的文件，不保留历史版本。
- HRV 和睡眠的空响应只留在原始档案里，不建表（用户晚上不戴表）。
- 只备份原始档案，不备份分析库。

**分析库**：SQLite，开启 WAL 模式。

- 写入：Rust 用 `rusqlite`（bundled feature）。
- 读取：Python 用 `sqlite3`、polars，或者用 DuckDB 的 sqlite 扩展直接查询。需要列式分析时用 DuckDB 读这个 SQLite 文件。
- 不选 DuckDB 文件作分析库：同一时间只能有一个进程写入，Jupyter 或仪表盘开着时会和同步冲突；而且 Rust crate 在 Windows 上编译慢。
- 不选 Parquet：Rust 侧依赖重；汇总表更新时只能整个文件重写。
- schema 由 Rust 定义：迁移 SQL 放在 Rust 项目里，导入 CLI 启动时自动执行。Python 对分析库只读。
- 单位一律用 FIT 的 SI 单位（m、m/s、s、bpm），配速只在 Python 展示时换算。
- 时间：`records.timestamp` 存 UTC。`activities` 同时存 `start_time_utc` 和 `start_time_local`（来自 `startTimeLocal`），按本地日期统计周跑量。

**表结构**：

- `records`：逐秒数据流的长表，每秒一行。主键 `(activity_id, timestamp)`，固定列包括 `heart_rate`、`speed`、`cadence`、`altitude`、`distance`、`lat`、`lon`、`power`、`temperature`，缺失值为 NULL。私有消息（`unknown_*`）不入库，需要时再解析原始 FIT。
- `laps`：手表的分段。
- `activities`：每个活动一行。从详情 JSON 里挑出有类型的列（类型、开始时间、距离、时长、平均/最大心率、爬升等），完整 JSON 只留在原始档案里。
- `daily_wellness`：每天一行（静息心率等），重新拉取时 upsert。
- `garmin_metrics`：每天一行，存 Garmin 三项指标的快照，作为参照。

**派生值**（TRIMP、EF、CTL 等）先在 Python 里每次现算，不落库。以后需要缓存时，写进一个独立的 `analysis.sqlite`，由 Python 拥有，不碰 Rust 的分析库。

**留给其他 ticket**：导入 CLI 需要一个"从原始档案重建分析库"的命令，什么时候触发它由同步方案决定。
