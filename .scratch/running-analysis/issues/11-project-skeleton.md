# 项目骨架与依赖

Type: grilling
Status: open
Blocked by: none

## Question

Rust 导入 CLI 和 Python 分析代码怎么组织在同一个仓库里，各用哪些依赖？

- 目录布局：Rust crate 和 Python 项目（`uv`）放在哪；`garminconnect` 三项指标的 PEP 723 小脚本放在哪。
- Rust 依赖：`reqwest`、`serde`、`rusqlite`（bundled）、`fitparser`，以及 SQLite 迁移怎么管理（手写 SQL 文件还是用 `rusqlite_migration` 之类的 crate）、CLI 参数解析、日志。
- Python 依赖：Python 版本，DataFrame 库选 polars 还是 pandas，Jupyter 怎么接入 `uv` 项目，是否用 DuckDB 读取分析库。
- 配置：数据目录路径、API key 所在位置，怎么让 Rust 和 Python 两边读到同一份配置（见 [存储方案](04-storage.md)：数据目录在仓库外，由配置或环境变量指定）。
- 仪表盘技术栈不在这里定，见 [仪表盘设计](08-dashboard-design.md)。

## Comments

- 2026-10-23（来自 [回填与增量同步策略](05-sync-strategy.md)）：导入 CLI 有 `sync`、`login`、`rebuild` 三个命令，其中 `login` 要调用 garminconnect 的 Python 小脚本，交互式读取密码。数据目录下除了 `raw/`，还有存放冷却标记的 `state/`。
- 2026-10-23（来自 [训练负荷模型与成绩预测方法](07-load-and-prediction.md)）：生理参数（HRmax、HRrest、LTHR）按生效日期配置，参考心率也在配置里；`races.csv` 由用户手工维护，放在数据目录。这些配置文件放在哪、用什么格式，在这里决定。
