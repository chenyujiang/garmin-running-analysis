# 02: Tracer bullet：从原始档案到仪表盘空状态

**What to build:** 打通整条链路的最窄路径。导入 CLI 把原始档案里的活动详情 JSON 重建进分析库；分析包只读打开分析库；本机仪表盘显示两种状态："还没有数据"的空状态（列出 `runsync sync` 和 `runsync login` 的步骤，以及数据目录位置），或者"已有 N 个活动，最近一次同步时间"。这个 ticket 立起两个项目的骨架，后面的 ticket 都在上面加功能。

**Blocked by:** 01（实施前提：工具链与凭据就位）

**Status:** ready-for-agent

来源：[实施 spec](../spec.md)，User Stories 1、2、6、8、27–29、31、48、60–63。

- [ ] 仓库根目录下有两个独立项目：Rust crate（二进制 `runsync`）和 uv 管理的 Python 项目（包 `running`，Python 3.14），不用任何 workspace
- [ ] 两边都按 `RUNNING_DATA_DIR` 找数据目录，默认 `%USERPROFILE%\running-data`，都读同一个 `config.toml`；文件缺失时给出明确错误
- [ ] 迁移用手写 SQL，编进二进制，用 `PRAGMA user_version` 记录版本，启动时在一个事务里执行；分析库开启 WAL
- [ ] `runsync rebuild` 删除分析库，从原始档案重建 `activities` 表（类型、`start_time_utc`、`start_time_local`、距离、时长、心率、爬升等，单位 SI），完全离线
- [ ] `runsync sync` 和 `runsync login` 的子命令已存在，暂时只提示"尚未实现"
- [ ] 分析包用 DuckDB 只读 `ATTACH` 分析库，用 polars 返回数据，不依赖 pandas
- [ ] FastAPI 只绑定 `127.0.0.1`，提供"数据状态"接口，并托管静态前端
- [ ] 前端是原生 ES modules，不用 node 构建；字体（Noto Serif SC、Noto Sans SC、IBM Plex Sans）本地托管；视觉基调按原型变体 A（新闻纸色底 `#f3efe6`、墨黑文字）；界面文字为中文
- [ ] Seam 1 测试：在手写的原始档案 fixture 上运行 `rebuild`，查询 SQLite 断言行数、单位、两个时间戳；迁移在空库和旧版本库上都能升到最新
- [ ] Seam 3 测试：用 `TestClient` 加合成的分析库，覆盖"没有分析库或库为空"和"有数据"两种返回
- [ ] `.gitignore` 加上 Rust 的 target 目录和 Python 的 `.venv`；配好 `nbstripout`；`rustfmt`、`clippy`、`ruff` 全部通过
- [ ] README 写明常用命令：构建、`rebuild`、启动仪表盘、跑两边的测试
