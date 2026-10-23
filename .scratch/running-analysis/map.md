# 个人跑步数据分析（Garmin）

Label: wayfinder:map

## Destination

一份可直接开工的技术方案：怎么从 Garmin Connect 国际版拿到全部数据、存在哪、用什么栈、三项核心分析（有氧能力、周跑量与训练负荷、比赛成绩预测）各怎么算。实施不在本地图内。

## Notes

- 领域：个人运动数据分析，单用户，本机运行。
- 账号：Garmin Connect 国际版（garmin.com），未开 MFA。
- 语言：数据导入 CLI（拉取、解析 FIT、写入存储）用 Rust，用户想借此学 Rust；分析部分用 Python。两边只通过存储交换数据。
- 分析：探索阶段用 Jupyter notebook；另做一个本机仪表盘。
- 设计：涉及界面的 ticket 一律调用 `impeccable`。
- 数据获取：接受非官方库的风险，需限速；手动导出 FIT / 账号数据导出作为后备。（具体途径见 Decisions so far。）
- 凭据：只在本机存 token / API key，密码不落盘。
- 数据范围：跑步活动（要逐秒数据流，不只是汇总）+ HRV、静息心率、睡眠。约 5 年历史，全部要。
- 用户晚上睡觉不戴手表：HRV 和睡眠实际上没有数据（试拉时最近 30 天全为空）；静息心率只来自白天佩戴，部分天缺失。
- 同步：先一次性回填全部历史，之后增量同步。
- 算法：Garmin 自带指标（Training Load、VO2max、Race Predictor）作参照，主模型自己算（透明、可调）。
- 每次 session 参考：`grilling`、`domain-modeling`；术语见根目录 `GLOSSARY.md`。

## Decisions so far

<!-- the index: one line per closed ticket -->

- [Garmin Connect 数据获取途径调研](issues/01-garmin-data-access.md)：官方 Personal API 做主力（活动、FIT、HRV、睡眠、静息心率）；`garminconnect` 只补 Training Load / VO2max / Race Predictor；账号数据导出作原始 FIT 存档；`garth` 已弃用。
- [有氧能力、训练负荷、成绩预测的算法调研](issues/02-analysis-methods.md)：推荐同心率 GAP 配速 + EF/decoupling；Banister TRIMP + CTL/ATL/TSB；VDOT 为主、Riegel 对照，全马加跑量修正；需要实测 HRmax、LTHR 和手工比赛清单。
- [Rust 导入 CLI 如何调用 Garmin 接口](issues/10-rust-api-coverage.md)：Personal API 用 `reqwest` 手写（没有现成 crate，spec 缺 `operationId`）；三项 Garmin 指标交给 `uv run` 调用的 Python 小脚本，不在 Rust 里重写登录；FIT 用 `fitparser`，原始字节先落盘。
- [试拉一小批真实数据](issues/03-trial-pull.md)：Personal API 约 200 次请求没有被限流，活动最早到 2021-08-06（约 1000–1500 条），下载的 FIT 与原始文件逐字节一致；`garminconnect` 的 mobile 登录被 429，但退到后备策略后登录成功，三项指标都拿到了。
- [存储方案](issues/04-storage.md)：原始档案（FIT、JSON）原样存在仓库外的数据目录，是事实来源；分析库用 SQLite（WAL），Rust 定义 schema 并写入，Python 只读，可随时从原始档案重建；全部活动类型入库，逐秒数据用一张长表。
- [回填与增量同步策略](issues/05-sync-strategy.md)：导入 CLI 只有 `sync`、`login`、`rebuild` 三个命令；手动触发；串行限速，靠原始档案是否已存在来续传，不存进度；每次重拉最近 7 天的数据以接住修正；429 立即停止并冷却 24 小时，两个数据源互不影响。
- [有氧能力指标的定义](issues/06-aerobic-metric.md)：主指标是参考心率 145 bpm 下的 GAP 配速（每次跑步在稳态段上拟合速度–心率直线）；按步频把每秒分成跑和走，配速和周跑量只算跑的部分；只算户外路跑；坡度用 Minetti 校正，温度第一版不校正只显示；按周取中位数，加 4 周滚动趋势线。
- [训练负荷模型与成绩预测方法](issues/07-load-and-prediction.md)：所有带心率的活动都算逐秒 Banister TRIMP（HRmax 192、HRrest 55 固定，参数按生效日期配置），CTL 42/ATL 7/TSB 只作相对指标；周跑量按自然周统计全部跑步；成绩预测用手工 `races.csv`，VDOT 为主、Riegel 对照，全马加周跑量修正，Garmin 预测作参照。
- [项目骨架与依赖](issues/11-project-skeleton.md)：仓库里放 `importer/`（Rust CLI `runsync`，blocking reqwest、手写 `user_version` 迁移）和 `analysis/`（uv、Python 3.14、polars + DuckDB、Jupyter）两个项目；个人数据、`config.toml`、`races.csv` 和 key 都放在 `RUNNING_DATA_DIR` 指向的仓库外数据目录。
- [分析仪表盘的设计](issues/08-dashboard-design.md)：报纸体育版视觉风格，布局选变体 A（首屏三栏：负荷、周跑量、成绩预测；下面是全宽有氧趋势图，带十字线读数），处理未同步、预测过期、数据不足三种状态；技术栈定为 FastAPI 加静态前端（手写 SVG），Streamlit 还原不了批注和排版；原型在 `prototype/dashboard` 分支。

## Not yet specified

- **数据质量与清洗**：光电心率异常、GPS 漂移、手表暂停/自动暂停、跑步机活动。看过真实数据之后才能说清楚要处理哪些问题。
- **温度校正**：有氧能力第一版不校正温度，只在趋势图上显示每周平均温度。看到真实数据里季节波动有多大之后，再决定要不要用外部历史气温做回归校正。

## Out of scope

- 写代码实施分析工具：本地图只产出方案。
- 多用户、云部署、手机访问：只给自己本机用。
- Garmin 官方 Connect Developer Program：只对企业开放，个人申请不现实。
