# 个人跑步分析工具：实施 spec

Label: ready-for-agent
Status: open

来源：地图 [个人跑步数据分析（Garmin）](../running-analysis/map.md) 和它下面已解决的 ticket。每条决定的理由和来源以各 ticket 的 Answer 为准，这里只汇总要实施的内容。术语见根目录 `GLOSSARY.md`，产品背景见 `PRODUCT.md`。

## Problem Statement

用户用 Garmin 手表跑步，账号里有从 2021-08-06 起约 1000–1500 个活动。Garmin Connect 给出的 Training Load、VO2max、Race Predictor 是黑盒：公式不公开，参数不能调，也看不出"同样心率下是不是跑得更快了"。Garmin 的平均配速还把跑完后走路的时间算进去，数字偏慢。用户想要一套自己算、每个数字都能追溯到公式和参数的分析，用来回答三个问题：

1. 最近的训练负荷够不够、是不是太多了。
2. 有氧能力在几个月到几年的尺度上是在进步还是退步。
3. 现在去比赛，各距离大概能跑多少。

数据现在只在 Garmin 那边，本机没有完整的原始档案，也没有可以查询的分析库。

## Solution

两个独立的程序，只通过数据目录交换数据：

- **导入 CLI `runsync`**（Rust）：把 Garmin 的全部历史和之后的新数据同步到本机。原始文件原样存进原始档案，同时解析写入 SQLite 分析库。三个命令：`sync`、`login`、`rebuild`，全部手动运行。
- **分析包 `running`**（Python）：只读分析库，计算有氧能力、训练负荷、周跑量和成绩预测。同一套计算给 Jupyter 用于深入探索，也给本机仪表盘用。仪表盘是只在 `127.0.0.1` 上运行的 FastAPI 服务加静态网页，用户每周打开一两次，几分钟看完"这周该怎么练"。

用户每次想看新数据，就运行一次 `runsync sync`，然后打开仪表盘。

## User Stories

**首次设置**

1. As a runner, I want to point both programs at one data directory through `RUNNING_DATA_DIR`, so that my personal data never lives inside the repo or its worktrees.
2. As a runner, I want the data directory to default to `%USERPROFILE%\running-data` when the variable is unset, so that I don't have to configure anything on a fresh machine.
3. As a runner, I want my Personal API key read from a file under `secrets/` in the data directory, so that the key is never in the repo and never printed.
4. As a runner, I want to run `runsync login` once and type my Garmin password interactively, so that only a token is stored and the password never touches disk.
5. As a runner, I want `runsync login` to store the garminconnect token under `secrets/` in the data directory, so that all credentials live in one place I can protect.
6. As a runner, I want one `config.toml` holding physiology parameters, reference HR and request intervals, so that the importer and the analysis read the same settings.
7. As a runner, I want physiology parameters (HRmax, HRrest, LTHR) listed with an effective date, so that changing them later recalculates only activities after that date.
8. As a runner, I want a clear error when the data directory, config file or key file is missing, so that I know exactly what to create.

**回填与同步**

9. As a runner, I want the first `runsync sync` to backfill my full history since 2021-08 in one run, so that I don't have to babysit batches.
10. As a runner, I want a progress bar during backfill, so that I can tell the roughly 75-minute run is moving.
11. As a runner, I want backfill to resume from where it stopped when I rerun `sync` after an interruption, so that nothing is downloaded twice and no progress file can go stale.
12. As a runner, I want each downloaded file parsed into the analysis database right away, so that partial results are usable even if the run is interrupted.
13. As a runner, I want later runs of `sync` to fetch only new activities, so that an incremental sync takes seconds or minutes.
14. As a runner, I want activities from the last 7 days refetched on every sync, so that renames and type changes I make in Garmin Connect show up.
15. As a runner, I want daily summaries for the last 7 days refetched and upserted, so that today's incomplete data and Garmin's later corrections are picked up.
16. As a runner, I want all activity types synced, not only runs, so that strength and cycling sessions count toward training load without a second backfill.
17. As a runner, I want Garmin's Training Status, VO2max and Race Predictor backfilled one day per week and snapshotted on every sync, so that I can compare my numbers with Garmin's.
18. As a runner, I want requests sent one at a time with a fixed pause (1.5 s for Personal API, 5 s for garminconnect), so that I don't get rate-limited or locked out.
19. As a runner, I want a data source that returns 429 or `CAPTCHA_REQUIRED` to stop immediately without retrying, so that I don't make a lockout worse.
20. As a runner, I want a cooldown marker written after a 429, so that syncs in the next 24 hours skip that source and tell me why and until when.
21. As a runner, I want the two data sources to fail independently, so that a garminconnect problem never blocks my activities from syncing.
22. As a runner, I want `sync` to tell me to run `runsync login` when the garminconnect token has expired, so that I know the fix without reading logs.
23. As a runner, I want `sync` to tell me to generate a new Personal API key when the key is rejected, so that I can recover when it expires around 2027-10.
24. As a runner, I want `sync` never to prompt for a password, so that it can run unattended later if I add a scheduled task.
25. As a runner, I want log verbosity controlled by `RUST_LOG`, so that I can debug a failing sync without changing code.
26. As a runner, I want a sync to be safe while Jupyter or the dashboard has the database open, so that I don't have to close them first.

**原始档案与重建**

27. As a runner, I want every FIT and JSON file stored exactly as Garmin returned it, so that the raw archive is the single source of truth.
28. As a runner, I want `runsync rebuild` to delete the analysis database and recreate it from the raw archive offline, so that parser fixes apply to all history without hitting Garmin.
29. As a runner, I want schema changes applied automatically by migrations at startup, so that upgrading the importer never requires a manual rebuild.
30. As a runner, I want a FIT file that fails to parse to be kept in the raw archive, logged and skipped, so that one bad file doesn't stop the whole sync or rebuild.
31. As a runner, I want to back up only the `raw/` directory, so that my backup stays small and everything else can be regenerated.

**分析（Jupyter）**

32. As a runner, I want every run's running pace computed from running seconds only, so that the walk after a run doesn't make it look slower.
33. As a runner, I want each second classified as running or walking by cadence, so that walk breaks in long runs are handled the same way.
34. As a runner, I want an aerobic value per run (GAP pace at reference HR 145 bpm, fitted on steady-state seconds), so that I can see whether I'm faster at the same effort.
35. As a runner, I want treadmill and trail runs excluded from the aerobic metric, so that unreliable pace and technical terrain don't distort the trend.
36. As a runner, I want runs with less than 10 minutes of steady state left out of the aerobic metric, so that intervals and short jogs don't add noise.
37. As a runner, I want hills corrected with Minetti's formula, so that hilly routes are comparable with flat ones.
38. As a runner, I want EF and decoupling for runs of 60 minutes or longer, so that I can judge my long-run durability.
39. As a runner, I want a TRIMP value for every activity with heart rate, so that all training counts toward load.
40. As a runner, I want activities without heart rate marked as missing load rather than estimated, so that gaps are visible.
41. As a runner, I want CTL (42 days), ATL (7 days) and TSB, so that I can see fitness, fatigue and freshness trends.
42. As a runner, I want weekly running distance by calendar week (Monday to Sunday, local time) plus a rolling 7 days, so that I can track volume both ways.
43. As a runner, I want to keep my races in a hand-maintained `races.csv`, so that only real all-out efforts drive predictions.
44. As a runner, I want 5K, 10K, half and full marathon predictions from VDOT, with Riegel and Garmin as comparisons, so that I can see how much the methods agree.
45. As a runner, I want the marathon prediction adjusted by my recent weekly distance, so that it doesn't overestimate me the way pure VDOT does.
46. As a runner, I want predictions marked stale when there is no race in the last 6 months, so that I'm not misled by old fitness.
47. As a runner, I want the same calculation functions available in Jupyter, so that what I explore there matches what the dashboard shows.
48. As a runner, I want notebook outputs stripped on commit, so that personal data never lands in git.

**仪表盘**

49. As a runner, I want the top of the dashboard to say whether my load this week is fine or spiking, so that I know what to do this week at a glance.
50. As a runner, I want a red headline when ATL/CTL exceeds 1.5, so that a load spike is impossible to miss.
51. As a runner, I want this week's and last week's distance next to a 12-week bar chart, with the unfinished current week greyed out, so that I can compare volume quickly.
52. As a runner, I want a prediction table with VDOT, Riegel and Garmin side by side and the basis stated underneath, so that I know which race it comes from.
53. As a runner, I want a full-width aerobic trend (weekly median dots, 4-week rolling line, race markers) with a weekly temperature chart below, so that I can read seasonal effects.
54. As a runner, I want to switch the aerobic trend between half a year, 1 year, 2 years and all, so that I can see both recent and long-term change.
55. As a runner, I want a crosshair readout of date, pace and temperature on hover, so that I can read exact values.
56. As a runner, I want weeks with fewer than 2 qualifying runs left blank on the chart, so that missing data isn't interpolated.
57. As a runner, I want tables of long runs (EF, decoupling above 5% in red) and recent races, so that I can review key sessions.
58. As a runner, I want a "how is this calculated" note beside each block, showing the formula and current parameters, so that every number explains itself.
59. As a runner, I want a red dot next to numbers that changed since my last visit and a "mark all as read" button, so that I can see what's new.
60. As a runner, I want an empty state with the `runsync sync` / `runsync login` steps and the data directory when nothing has been synced, so that first use isn't a blank page.
61. As a runner, I want the dashboard reachable only from my own machine, so that my health data is never exposed to the network.
62. As a runner, I want the dashboard to work offline with self-hosted fonts, so that no request leaves my machine.
63. As a runner, I want interface text in Chinese with CTL, ATL, TSB, VDOT, EF and TRIMP kept in English, so that the terms match what I read elsewhere.

## Implementation Decisions

**整体结构**

- 仓库根目录下两个独立项目：Rust crate（二进制 `runsync`）和 uv 管理的 Python 项目（包 `running`），不用 Cargo workspace，也不用 uv workspace。仪表盘是 Python 项目的一部分。
- 两边只通过数据目录交换数据。分析库的 schema 由 Rust 拥有，Python 一律只读打开。
- 数据目录由 `RUNNING_DATA_DIR` 指定，默认 `%USERPROFILE%\running-data`。结构：`config.toml`、`races.csv`、`secrets/`（Personal API key、garminconnect token）、`raw/`（原始档案）、`state/`（冷却标记）、`running.sqlite`（分析库）、可选的 `analysis.sqlite`（Python 的派生值缓存）。
- `config.toml` 两边共用，Rust 用 `toml` crate 读，Python 用 `tomllib` 读。形状如下（来自 ticket「项目骨架与依赖」）：

```toml
[aerobic]
reference_hr = 145

[[physiology]]
effective_from = 2021-08-01
hr_max = 192
hr_rest = 55
lthr = 170
```

  其余阈值（步频 140 spm、稳态段的各项条件、请求间隔）也写进配置，代码里给默认值。

**导入 CLI `runsync`**

- 依赖：`reqwest`（`blocking`、`json`、`rustls-tls`，不用 tokio）、`rusqlite`（bundled）、`fitparser`、`clap`（derive）、`anyhow`、`log` + `env_logger`、`indicatif`、`serde`、`serde_json`、`toml`、`zip`、`chrono`。工具链为 rustup stable，`x86_64-pc-windows-msvc`，edition 2024。
- **数据源 trait**：把一个数据源抽象成一个 trait，两个实现分别是 Personal API 客户端和 garminconnect 小脚本。同步逻辑只依赖这个 trait（测试 seam，见下）。错误分成三类，用一个小 enum 表示：限流（429 或 `CAPTCHA_REQUIRED`）、凭据失效、其他。
- **Personal API 客户端**：用 `reqwest` + `serde` 手写，只实现用到的 GET 接口：活动列表翻页、活动详情、FIT 下载（zip，解出里面唯一的 FIT 后丢掉 zip）、每日汇总（7 天一个区间）。每次运行 `sync` 时用 key 换一次 access token（`POST` 到 personal-api-key token 接口，请求头 `Authorization: ApiKey <key>`，响应是纯文本 JWT，过期时间取 `exp`），接近过期时再换。token 不写盘。
- **garminconnect 小脚本**：一个 PEP 723 Python 脚本，放在 Rust 项目里，依赖 `garminconnect`，CLI 用 `uv run --script` 调用，路径在编译时由 `CARGO_MANIFEST_DIR` 确定。子命令：`login`（用 `getpass` 读密码，只保存 token）和三项指标的查询。stdout 只输出 JSON，退出码区分成功、限流、认证失败、其他错误。不在 Rust 里重写 Garmin 登录。
- **原始档案布局**：Personal API 的 `activities/<activityId>.fit` 和 `activities/<activityId>.json`、`daily_summaries/<YYYY-MM-DD>.json`；garminconnect 的 `<metric>/<YYYY-MM-DD>.json`；账号数据导出包原样放在 `export/<导出日期>/`，由 `runsync import-export` 解析（见 ticket 17）。重新拉取的数据覆盖同名文件，不保留历史版本。HRV 和睡眠的空响应只留在原始档案里，不建表。
- **同步算法**：
  - 新活动：活动列表从最新往前翻页，直到某一页的活动在原始档案里全都已有为止。
  - 最近 7 天内的活动：重新拉取详情 JSON 并覆盖；FIT 只在缺失时下载。
  - 每日汇总：每次重新拉取最近 7 天，覆盖并 upsert。
  - Garmin 三项指标：回填时每周取一天；之后每次同步存当天快照。接口能否按日期查历史要在实施时验证，查不了就只存快照。
  - 续传只看原始文件是否已存在，不存进度。每下载一个文件就解析写库。
  - 两个数据源串行处理，各自独立：一个出错不影响另一个。
  - 限流：立即停掉这个数据源，在 `state/` 写冷却标记（含时间和原因）。24 小时内跳过并说明原因。凭据失效：停掉这个数据源，提示运行 `login`（garminconnect）或重新生成 key（Personal API）。
- **迁移**：手写 SQL 文件，用 `include_str!` 编进二进制，用 `PRAGMA user_version` 记录版本，启动时在一个事务里依次执行未执行的文件。不用 `rusqlite_migration`。分析库开启 WAL。
- **`rebuild`**：删除分析库，按 schema 重建，遍历原始档案全部重新解析。完全离线。
- **FIT 解析**：`fitparser`。已知 issue #58：开发者字段出现在其描述之前时整个文件解析失败。这类文件记日志后跳过，`rustyfit` 作为备选。私有消息（`unknown_*`）不入库。

**分析库 schema**（单位一律 SI：m、m/s、s、bpm；时间戳 UTC）

- `activities`：每个活动一行。从详情 JSON 里挑出有类型的列：activity_id、类型、`start_time_utc`、`start_time_local`、距离、时长、平均和最大心率、爬升等。完整 JSON 只留在原始档案里。
- `records`：逐秒数据流长表，主键 `(activity_id, timestamp)`，列有 `heart_rate`、`speed`、`cadence`、`altitude`、`distance`、`lat`、`lon`、`power`、`temperature`，缺失为 NULL。`cadence` 按 FIT 原样存单脚步频。
- `laps`：手表的分段。
- `daily_wellness`：每天一行（静息心率等），upsert。
- `garmin_metrics`：每天一行，存三项 Garmin 指标的快照。

**分析包 `running`**

- Python 3.14，依赖 polars 和 DuckDB（`ATTACH` SQLite，只读），不直接依赖 pandas。jupyterlab 放在 dev 依赖组。用 `nbstripout` 在提交时清掉 notebook 输出。派生值每次现算，不落库；以后需要缓存再写进 `analysis.sqlite`。
- 模块按领域划分：配置与数据读取；跑和走的分类与跑步配速；有氧能力；训练负荷；周跑量；成绩预测。notebook 和仪表盘都只调用这些模块的公开函数。
- **跑和走**：步频 ×2 得到 spm，10 秒平滑，≥140 spm 算跑；连续走不到 10 秒的仍算跑。跑步配速 = 跑的秒的距离 ÷ 跑的秒的时长。Garmin 的平均配速作参照保留。
- **有氧能力**：只算户外路跑（`running` 类型，排除跑步机和越野）。稳态段：去掉前 10 分钟；心率和速度各做 30 秒滚动平滑；只保留同时满足以下条件的秒：在跑、心率在参考心率 ±15 bpm 内、60 秒内速度变化 ≤5%、没有暂停、心率与 spm 的差 ≥5。有效时长不足 10 分钟的跑步不计入。坡度用平滑后的气压海拔、按 30 秒距离窗口计算，限制在 ±15%，用 Minetti 2002 的 `Cr(i)` 把速度换成 GAP 速度。在稳态秒上拟合 `GAP速度 ~ 心率` 的直线，取参考心率处的值作为这次跑步的有氧能力值。按周取有效跑步的中位数，不足 2 次的周留空，再算 4 周滚动中位数。温度取 FIT 的手表温度，只按周求平均用于显示，不做校正。
- **EF 与 decoupling**：EF = GAP 速度 ÷ 心率，只用稳态段。decoupling 只对 ≥60 分钟的跑步计算，>5% 标出。
- **训练负荷**：逐秒 Banister TRIMP，男性系数 `0.64·e^(1.92x)`，`x = (HR − HRrest) / (HRmax − HRrest)`，参数按活动日期取当时生效的一组。所有带心率的活动都计入；没有心率的记为缺失。CTL 用 42 天 EWMA，ATL 用 7 天，TSB = CTL − ATL。ATL/CTL > 1.5 标为"负荷突增"。
- **周跑量**：只统计跑步类活动（路跑、跑步机、越野都算），只算跑的秒的距离。按 `start_time_local` 的自然周（周一到周日）统计，另给滚动 7 天的值。
- **比赛清单**：`races.csv`，字段 `date, activity_id, distance_m, time_s, all_out, note`。缺失或格式错误时给出明确提示。
- **成绩预测**（5K、10K、半马、全马）：取最近 6 个月内最好的一场 `all_out` 比赛算 VDOT，再换算各距离。Riegel 作对照：有 2 场以上比赛时拟合个人指数，否则用 1.06。全马按 Vickers 2016 用最近 8 周平均周跑量修正。Garmin Race Predictor 的值作参照。6 个月内没有比赛时标为过期，不给预测值。

**仪表盘**

- FastAPI 只绑定 `127.0.0.1`，没有账号。它只做一件事：调用 `running` 计算，以 JSON 返回。同一服务提供静态前端文件。
- JSON 接口按仪表盘的区块划分：负荷（CTL/ATL/TSB 当前值和近 12 周序列、突增标志）、周跑量（本周、上周、滚动 7 天、近 12 周）、成绩预测（三种方法、依据、是否过期）、有氧能力趋势（按范围参数返回周序列，含空周和每周温度）、长距离表、最近比赛、数据状态（是否已同步、最近同步时间、数据目录）。确切的路径和字段名在实施时定，并作为 Seam 3 的契约。
- 每个区块的返回里带上"怎么算的"所需的公式名和当前参数，前端只负责展示。
- 前端：原生 ES modules + 手写 SVG 图表，不用 node 构建，不引入图表库。字体（Noto Serif SC、Noto Sans SC、IBM Plex Sans）本地托管。"上次打开以来变化"的红点用浏览器 localStorage 记录上次看到的值，服务端不写任何东西。
- 视觉与布局以原型分支 `prototype/dashboard`（commit `8013fab`）里 HTML 原型的变体 A 为准：报纸体育版风格，新闻纸色底 `#f3efe6`、墨黑文字、红色 `#b0281f` 只用于批注和警告；数字用 tabular-nums；每张图最多 2 条编辑式批注。有氧能力图使用原型变体 C 的十字线读数。原型用的是合成数据，正式版换成接口数据。
- 三种状态：未同步（空状态，显示同步步骤和数据目录）、预测过期（预测表变淡，红字说明最近一场比赛的日期，提示更新 `races.csv`）、数据不足的周（点留空，不插值）。

## Testing Decisions

好的测试只通过外部行为验证结果：给定输入（fixture 文件、合成数据库、假数据源），检查输出（数据库内容、文件系统状态、命令输出、JSON），不检查内部函数怎么调用、中间结构长什么样。测试 seam 只有下面这些，不为了测试再加新的抽象层。

- **Seam 1：导入 CLI，原始档案到分析库。** 准备一个小型的原始档案 fixture 目录（手写的详情 JSON、每日汇总 JSON，以及合成的小 FIT 文件），在上面运行 `rebuild`，然后直接查询生成的 SQLite，断言：各表行数；单位为 SI；`start_time_utc` 和 `start_time_local` 正确；同一天重复写入时是 upsert；无法解析的 FIT 被跳过而不是中断；迁移在空库和旧版本库上都能执行到最新版本。fixture 不含真实 GPS，可以提交。读取真实 FIT 的集成测试从数据目录读文件，标 `#[ignore]`，用 `cargo test -- --ignored` 手动运行。
- **Seam 2：导入 CLI，`sync` 对接数据源 trait。** 用内存里的假数据源驱动 `sync`，断言原始档案和 `state/` 的结果：原始文件已存在时跳过（续传）；翻页在整页都已存在时停止；最近 7 天的详情和每日汇总被覆盖；某个数据源返回限流后写冷却标记，24 小时内再次运行时跳过这个数据源，超过 24 小时恢复；一个数据源失败时另一个照常完成；凭据失效时输出相应提示。不测真实 HTTP，也不调用真实的 Python 小脚本。
- **Seam 3：仪表盘 JSON 接口。** pytest + FastAPI `TestClient`，测试启动时用合成数据生成一个小 `running.sqlite`（用与 Rust 相同的 schema），再加 `config.toml` 和 `races.csv`。断言各接口返回的数值，以及三种状态：没有分析库或分析库为空；6 个月内没有比赛；某周有效跑步不足 2 次。
- **公式级测试（Seam 3 之外唯一的补充）**：TRIMP、VDOT 换算、Riegel、Vickers 修正、Minetti `Cr(i)` 这几个公式，用 pytest 直接测 `running` 的公开函数，用原始出处里的数值核对。其余逻辑（稳态段筛选、跑走分类、周聚合、EWMA）都通过 Seam 3 测试。
- 仓库目前没有代码，也就没有现成的测试可以参照。
- 格式化和 lint：Rust 用 `rustfmt` + `clippy`，Python 用 `ruff`。不加 pre-commit hook，不加 `justfile`，常用命令写进 README。

## Out of Scope

- 数据质量与清洗（光电心率异常、GPS 漂移、暂停和自动暂停、跑步机活动的问题）：第一次回填完成后，在 Jupyter 里统计实际情况，再另开 ticket 决定。
- 温度校正：第一版只显示每周平均温度。要不要用外部历史气温（会把位置发给第三方）做回归校正，等看过全部历史的季节波动后再决定。
- 拟合完整的 Banister 表现模型；把 ACWR 当受伤预警。
- 解析账号数据导出包里活动、FIT、每日汇总和三项 Garmin 指标以外的内容（睡眠、个人资料等）：只随整个包原样存档（ticket 17）。
- HRV 和睡眠分析：用户晚上不戴表，没有数据。
- 定时自动同步（Windows 任务计划程序）。
- 多用户、账号、云部署、手机访问。
- Tauri 或其他桌面外壳；Streamlit。
- Garmin Connect Developer Program。

## Further Notes

- **实施前提**：本机还没有 Rust。需要先装 rustup，以及带 C++ 工作负载的 Visual Studio Build Tools（`rusqlite` 的 bundled feature 要用它编译 SQLite）。
- **凭据**：用户自己把仓库根目录的 `.env` 移到数据目录的 `secrets/` 下，`garminconnect` 的 token 从 `~/.garminconnect` 移过去。实施时不要读取、打印或提交任何 key 或 token 的内容。Personal API key 大约 2027-10 到期。
- **登录风险**：本机的 garminconnect mobile 登录策略已经被 429，需要退到后备策略。尽量复用 token，少登录；调试时不要反复调用 `login`。
- **公式出处**：VDOT 表、Vickers 2016 系数、Banister TRIMP 系数原文在调研时没有读到，写代码前要核对原始出处（见 ticket「有氧能力、训练负荷、成绩预测的算法调研」和分支 `research/analysis-methods`）。
- **待实施时验证**：garminconnect 三项指标能否按日期查历史；`fitparser` 和 `rustyfit` 在 Windows 上能否构建；参考心率 145 是否接近真实数据里轻松跑心率的中位数，偏离明显时调整一次。
- **账号数据导出**：导出包已到（2026-10），由 `runsync import-export <zip>` 存进 `raw/export/<导出日期>/` 并解析，代替大部分 API 回填（ticket 17）。
- 研究资料在分支 `research/garmin-data-access`、`research/analysis-methods`、`research/rust-api-coverage`，原型在 `prototype/dashboard`，都不合并进 main。
