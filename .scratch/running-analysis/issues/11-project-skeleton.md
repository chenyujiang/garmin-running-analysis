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
