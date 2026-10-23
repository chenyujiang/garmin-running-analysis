# 项目骨架与依赖

Type: grilling
Status: resolved
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

## Answer

2026-10-23 与用户逐条讨论后确定。

**目录布局**：仓库根目录下放两个独立项目，不用 Cargo workspace，也不用 uv workspace。

```
importer/                     Rust crate，二进制名 runsync
  src/
  migrations/                 0001_init.sql …
  scripts/garmin_metrics.py   PEP 723 小脚本：三项 Garmin 指标 + login
analysis/                     uv 项目
  src/running/                aerobic.py、load.py、predict.py …
  notebooks/
  tests/
GLOSSARY.md
.scratch/                     地图和试拉脚本，保持原样
```

- CLI 在编译时用 `CARGO_MANIFEST_DIR` 拿到 `scripts/garmin_metrics.py` 的绝对路径，通过 `uv run --script` 调用。单用户本机运行，这样就够了。
- 命令：`runsync sync`、`runsync login`、`runsync rebuild`。
- `.gitignore` 要加上 `importer/target/` 和 `analysis/.venv/`。

**Rust**：

- 工具链：rustup stable，`x86_64-pc-windows-msvc`，edition 2024。
- HTTP：`reqwest`，开 `blocking`、`json`、`rustls-tls` 三个 feature，不引入 tokio。请求全部串行，用不上异步；rustls 不依赖系统 OpenSSL。
- 迁移：手写。`migrations/NNNN_*.sql` 用 `include_str!` 编进二进制，用 `PRAGMA user_version` 记录版本，启动时在一个事务里依次执行还没跑过的文件。不用 `rusqlite_migration`，因为它的版本和 `rusqlite` 绑定，升级时要两边一起改。
- 错误处理：`anyhow`，另写一个小 enum 区分"数据源被限流（429/CAPTCHA）""凭据失效""其他错误"。`sync` 根据它决定是停掉这个数据源并写冷却标记，还是提示运行 `login`。
- 其他依赖：`clap`（derive）、`log` + `env_logger`（用 `RUST_LOG` 控制级别）、`indicatif`（回填进度条）、`serde`、`serde_json`、`toml`、`zip`、`chrono`、`fitparser`、`rusqlite`（bundled）。

**Python**：

- `analysis/` 用 `.python-version` 固定在 3.14。PEP 723 脚本写 `requires-python = ">=3.12"`，依赖 `garminconnect`，环境由 uv 自己管理。
- 主力用 polars。读分析库用 DuckDB（`ATTACH` SQLite 文件），一律只读打开。不直接依赖 pandas。
- `jupyterlab` 放在 uv 的 dev 依赖组，用 `uv run jupyter lab` 启动；在 VS Code 里用时，内核选 `analysis/.venv`。
- 计算逻辑写在 `analysis/src/running/` 包里，notebook 只负责调用和画图，仪表盘以后复用同一套代码。
- 用 `nbstripout` 在提交时清掉 notebook 的输出，因为输出里有个人数据。

**数据目录与配置**：数据目录由环境变量 `RUNNING_DATA_DIR` 指定，默认 `%USERPROFILE%\running-data`。个人数据和配置都放在这里，仓库里只有代码。

```
running-data/
  config.toml          生理参数（按生效日期）、参考心率、限速间隔
  races.csv            手工维护的比赛清单
  secrets/
    personal_api.key   裸 key，与现在的 .env 格式相同
    garminconnect/     garminconnect 的 token，从 ~/.garminconnect 移过来
  raw/                 原始档案，唯一需要备份的部分
  state/               冷却标记
  running.sqlite       分析库，Rust 写入
  analysis.sqlite      派生值缓存，Python 拥有，可选
```

- Rust 用 `toml` crate 读 `config.toml`，Python 用标准库 `tomllib` 读，两边读同一个文件。示例：

```toml
[aerobic]
reference_hr = 145

[[physiology]]
effective_from = 2021-08-01
hr_max = 192
hr_rest = 55
lthr = 170
```

- 仓库根目录的 `.env` 由用户自己移到 `secrets/personal_api.key`。这样 key 不会出现在任何 worktree 里，也不会进入备份。

**测试**：真实 FIT 带 GPS 轨迹，不进 git。

- Rust：JSON 解析和迁移的单元测试用手写的小 fixture，提交进仓库。FIT 解析的集成测试从数据目录读真实文件，标成 `#[ignore]`，用 `cargo test -- --ignored` 手动跑。
- Python：pytest，用合成的 polars DataFrame 测 TRIMP、稳态段、VDOT 等计算。

**格式化与 lint**：Rust 用 `rustfmt` + `clippy`，Python 用 `ruff`。不加 pre-commit hook，也不加 `justfile`，常用命令写进 README。

**实施前提**（不开 ticket，实施不在本地图内）：本机还没有 Rust。需要先装 rustup，以及带 C++ 工作负载的 Visual Studio Build Tools（`rusqlite` 的 bundled feature 要用它编译 SQLite）。
