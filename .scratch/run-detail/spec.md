# 单次跑步详情与分析报告：实施 spec

Label: ready-for-agent
Status: open

来源：用户 2026-11-04 的需求和对方案的确认（活动列表加链接进详情页；地图只画 SVG 路线形状，不要底图；分析报告用固定规则生成）。上一阶段的 spec 见 [running-tool/spec.md](../running-tool/spec.md)，偏离见 [running-tool/deviations.md](../running-tool/deviations.md)。术语见根目录 `GLOSSARY.md`，产品背景见 `PRODUCT.md`。

## Problem Statement

现在的仪表盘只有汇总：周跑量、训练负荷、有氧能力趋势、长距离表、成绩预测。用户跑完一次，想看这一次本身：配速和心率怎么变化、每公里和每圈跑得怎样、这次算轻松跑还是节奏跑、有氧能力比最近是好是差、心率有没有漂移、天热有没有影响。这些现在只能去 Jupyter 里自己查，或者回到 Garmin Connect 看它的黑盒数字。

## Solution

仪表盘加两个页面，都在同一个静态前端里，用 hash 路由：

- **活动列表** `#/runs`：按开始时间倒序列出活动，可以按类型和距离筛选，分页。每一行链接到详情页。首页的长距离表和最近比赛表里的活动也链接到详情页。
- **活动详情** `#/run/<activity_id>`：概要、逐秒曲线、分段（圈和每公里）、路线形状、本次指标，最上面是一段用固定规则生成的中文分析报告。

全部用分析库里已有的数据和 `running` 包里已有的公式现算，不改 Rust 端，不改 schema，不落库。报告里每句话都能追溯到一个规则和它的参数。数据不离开本机：路线只画形状，不加载任何在线底图。

## User Stories

**进入详情页**

1. As a runner, I want a list of my activities, newest first, so that I can find the run I just did.
2. As a runner, I want to filter the list by activity type (running types by default, or all types), so that strength and cycling sessions don't crowd it.
3. As a runner, I want to filter the list by minimum distance, so that I can find long runs quickly.
4. As a runner, I want each list row to show date, type, name, distance, duration, running pace and average HR, so that I can recognise the run before opening it.
5. As a runner, I want the list paged, so that the page stays fast with 1500 activities.
6. As a runner, I want the runs in the long-run table and recent-race table on the home page to link to their detail page, so that I can drill down from the summary.
7. As a runner, I want the detail page to have its own URL, so that I can bookmark it or reopen it after a refresh.
8. As a runner, I want a clear message when the activity id doesn't exist, so that a stale bookmark doesn't show a blank page.

**概要与曲线**

9. As a runner, I want the summary to show distance, duration, running pace (walking left out), Garmin's average pace as reference, average and max HR, cadence (spm), elevation gain and air temperature, so that I see the run at a glance.
10. As a runner, I want HR, pace, GAP pace, altitude and cadence charts on one shared time axis, so that I can see how they move together.
11. As a runner, I want pauses, walking stretches and steady-state seconds marked on the charts, so that I can see which seconds the metrics used.
12. As a runner, I want a crosshair readout on the charts, so that I can read exact values at any moment.

**分段**

13. As a runner, I want a table of the watch laps with pace, HR and cadence, so that I can review interval sessions as I ran them.
14. As a runner, I want a table of per-kilometre splits with running pace, GAP pace, HR and cadence, so that I can compare kilometres on a hilly course.

**路线形状**

15. As a runner, I want the route drawn as a shape with start and finish marked, so that I recognise the course.
16. As a runner, I want no map tiles loaded, so that the location of my runs is never sent to a third party.

**本次指标**

17. As a runner, I want this run's TRIMP, so that I know how much it adds to training load.
18. As a runner, I want time in each HR zone, so that I can see how hard the run really was.
19. As a runner, I want this run's aerobic value (pace at reference HR) when the run qualifies, and the reason when it doesn't, so that I trust the trend chart.
20. As a runner, I want EF and, for runs of 60 minutes or more, decoupling, so that I can judge endurance on this run.

**分析报告**

21. As a runner, I want a short report at the top of the detail page, so that I get the conclusions without reading every chart.
22. As a runner, I want the report to classify the run (easy, tempo, interval, long, mixed), so that I can check the week's mix.
23. As a runner, I want the report to compare this run's aerobic value with my recent 4-week median, so that I know whether it was a good day.
24. As a runner, I want the report to say whether HR drifted (decoupling), so that I know whether the pace was sustainable.
25. As a runner, I want the report to describe the pacing (even, positive or negative split, on GAP pace), so that hills don't fool the verdict.
26. As a runner, I want the report to say what the run did to load (TRIMP, share of the week, TSB before and after), so that I can plan the next days.
27. As a runner, I want the report to warn when the air was hot, so that a high HR has an explanation.
28. As a runner, I want every report sentence to show the rule and thresholds behind it, so that I can disagree with a rule and change its parameter.
29. As a runner, I want the report thresholds in `config.toml`, so that I can tune them without editing code.
30. As a runner, I want the report to say what it couldn't judge and why (no HR, no GPS, too short), instead of guessing.

## Implementation Decisions

**不变的部分**

- 不改 Rust 端，不加迁移，不改分析库 schema。全部用现有表：`activities`、`records`、`laps`、`hourly_weather`。
- 派生值每次现算，不落库。分析库照旧只读打开。
- 仪表盘仍只绑定 `127.0.0.1`，只读，不写任何东西。

**分析包 `running`**

- 新模块 `running/activities.py`：活动列表。`activity_list(type_filter="running", min_distance_m=None, page=1, page_size=50, root=None)`。`type_filter` 为 `running`（`RUNNING_TYPES` 的 9 种）或 `all`。每行：`activity_id, activity_type, activity_name, start_time_local, distance_m, duration_s, running_pace_s_per_km`（跑步类才有），`avg_hr_bpm`。返回总数，供前端分页。
- 新模块 `running/detail.py`：单次详情，`activity_detail(activity_id, root=None)`，一次返回整个详情页需要的数据。拆成内部函数：概要、逐秒序列、分段、路线、本次指标。复用现有函数，不复制公式：
  - 跑走分类和跑步配速：`runwalk.classify_records`、`running_summaries`。
  - 稳态段、GAP：`aerobic.steady_state`、`gap_speed`；本次有氧能力值用 `aerobic_runs` 的同一套条件。
  - 气温：`aerobic.air_temperature`。
  - TRIMP：`load` 里的逐秒算法；TSB 前后取 `training_load` 的序列（TSB 用前一天 CTL/ATL，见 deviations 第 2 条）。
  - EF 与 decoupling：`longruns` 的同一套口径（稳态段去掉心率带条件，稳态时间对半切）。门槛是户外路跑、有逐秒心率、GPS 可用、不限心率的稳态时间 ≥ 10 分钟；所以心率整段在 145 ± 15 之外的跑没有有氧能力值，仍有 EF。
- **逐秒序列**：服务端降采样到最多 1500 个点（按时间等分成桶，桶内取均值，暂停时段不跨桶）。暂停、走路、稳态以区间列表返回（`[start_s, end_s]`，从活动开始算起的秒数），不逐点返回标志。
- **每公里分段**：按 `records.distance` 切，每满 1000 m 一段，最后不足 1 km 的一段单独列出并标明距离。每段给跑步配速（只算跑的秒）、GAP 配速、平均心率、平均 spm、海拔升降。
- **圈分段**：直接取 `laps` 表；`avg_cadence` ×2 换成 spm。
- **路线形状**：只用有 `lat`/`lon` 的秒。等距矩形投影到以路线中心为原点的米制平面，再整体缩放到 `[0, 1]`，保留长宽比；用 Douglas–Peucker 简化到最多 500 个点。只返回归一化后的 `x, y`、起点和终点在序列里的下标、以及比例尺（`[0, 1]` 的 1 个单位对应多少米）。**接口不返回任何绝对经纬度或中心点。** 没有 GPS 的活动（跑步机等）返回 `route: null` 并说明原因。
- **心率区间**：按 LTHR 的百分比分 5 区（Friel 跑步区间）：Z1 < 85%，Z2 85–89%，Z3 90–94%，Z4 95–99%，Z5 ≥ 100%。LTHR 按活动日期取当时生效的 `[[physiology]]`。边界放在新的 `[zones]` 配置里，列表形式 `lthr_pct = [85, 90, 95, 100]`。只统计有心率的秒；暂停不计。
- **分析报告**：新模块 `running/report.py`，`run_report(detail, context) -> Report`，输入是详情数据和最近的上下文（前 4 周有效跑的有氧能力中位数、当周 TRIMP、TSB 序列），输出一组条目。每个条目：`rule`（规则名）、`verdict`（短结论，用于着色：`good`、`neutral`、`watch`、`unknown`）、`text`（一句中文）、`params`（用到的阈值和实际数值）。报告是纯函数，便于测试。规则：
  1. **训练类型**（按顺序判，命中即止）：
     - 间歇：30 秒平滑速度高于本次跑步中位速度 ≥ 15%、持续 ≥ 60 秒的段 ≥ 3 段，且段间有更慢的恢复段。
     - 节奏跑：Z3–Z4 合计 ≥ 50% 的跑的时间，并且其中有连续 ≥ 15 分钟的一段。
     - 长距离：时长 ≥ 60 分钟，且 Z1–Z2 合计 ≥ 70%。
     - 轻松跑：Z1–Z2 合计 ≥ 80%。
     - 其余为混合。
  2. **有氧能力对比**：本次有氧能力值与本次所在周之前 4 周（`[aerobic] rolling_weeks`）所有计入有氧能力的跑步的中位数比较，不要求每周的次数，也不先取周中位数。快 ≥ 2% 为 good，慢 ≥ 2% 为 watch，其间持平。本次不计入有氧能力时，说明原因（不是户外路跑、稳态不足 10 分钟、没有心率等），verdict 为 unknown。
  3. **心率漂移**：时长 ≥ 60 分钟时报告 decoupling，> 5% 为 watch，≤ 5% 为 good。不足 60 分钟时只给 EF，不判漂移。
  4. **配速分布**：按距离把跑的秒对半分，比较前后两半的 GAP 配速。后半快 ≥ 2% 为负分割（negative split），慢 ≥ 2% 为正分割，其间为匀速。间歇跑不判配速分布。
  5. **负荷**：本次 TRIMP、占当周（周一到周日）TRIMP 的比例、当天跑前和第二天的 TSB。当天 ATL/CTL > 1.5 时沿用"负荷突增"的提示，verdict 为 watch。
  6. **气温**：本次平均气温（Open-Meteo）≥ `hot_week_c`（22 °C）时提示心率可能因热偏高，verdict 为 watch。没有气温数据时这一条不出现。
- 报告阈值放在新的 `[report]` 配置里，代码给默认值：`interval_speed_ratio = 0.10`（原为 0.15，见 ticket 08）、`interval_min_s = 60`、`interval_min_reps = 3`、`tempo_share = 0.5`、`tempo_min_s = 900`、`long_easy_share = 0.7`、`easy_share = 0.8`、`aerobic_change = 0.02`、`split_change = 0.02`。`hot_c` 不另设，沿用 `[aerobic].hot_week_c`。
- 非跑步类活动：详情页照样打开，给概要、心率曲线、心率区间和 TRIMP；跑步专属的部分（跑步配速、每公里分段、有氧能力、配速分布、训练类型）返回 null，并带原因"仅跑步类活动"。

**仪表盘**

- 新接口：
  - `GET /api/activities?type=running|all&min_km=<float>&page=<int>&page_size=<int>`（page_size 1–200，默认 50）。
  - `GET /api/activities/{activity_id}`：详情加报告，一次返回。不存在时 404，JSON 里带中文说明。
- 每个区块的返回照旧带 `method{name, description, params}`，前端"怎么算的"直接显示。
- 前端：hash 路由放在 `app.js`。`#/`（或空）是现有首页，`#/runs` 是列表，`#/run/<id>` 是详情。页头加一个"全部活动"的链接。新模块 `static/runs.js`（列表）、`static/run.js`（详情），图表沿用 `svg.js` 和有氧能力图的十字线读数写法。不引入图表库、地图库，不加 node 构建。
- 视觉沿用变体 A：新闻纸底色、墨黑文字，红色 `#b0281f` 只用于 watch 级别的报告条目和警告；数字用 tabular-nums。报告放在详情页最上面，每条一行，结论在前，规则和数值可以展开。
- 首页的长距离表、最近比赛表里，有 `activity_id` 的行加上链接。

**文档**

- `PRODUCT.md` 的"Deeper digging happens in Jupyter"改成：单次跑步的复盘在仪表盘的详情页，跨活动的深入探索仍在 Jupyter。
- `GLOSSARY.md` 加词条：心率区间、训练类型、分析报告、配速分布。
- `README.md` 加新配置段 `[zones]`、`[report]` 和新接口的简短说明。

## Testing Decisions

沿用上一阶段的原则：只通过外部行为验证。新功能全部走 Seam 3（pytest + FastAPI `TestClient`，合成的 `running.sqlite`），不新增 seam。

- **列表接口**：排序、类型筛选、最小距离、分页总数、`page_size` 越界返回 422。
- **详情接口**：
  - 404 和中文说明。
  - 概要数值；降采样后点数 ≤ 1500，暂停区间不跨桶。
  - 每公里分段的段数和最后一段的距离；圈分段的 spm 换算。
  - 心率区间：按合成心率算出的各区时长，以及 LTHR 换参数后按日期取值。
  - 非跑步类活动的 null 和原因。
- **路线隐私**：合成数据用一个固定的虚构坐标（不是用户的真实位置，写在测试文件里）。断言返回的 JSON 里没有任何接近这个坐标的数（遍历 JSON 里所有数字，和原始经纬度比较），`x, y` 都在 `[0, 1]`，长宽比保持，点数 ≤ 500。没有 GPS 时 `route` 为 null。
- **报告规则**：每条规则用一个合成活动触发命中和不命中两种情况，断言 `rule`、`verdict` 和 `params` 里的数值。例如：3 段快跑的活动判为间歇，2 段的不判；后半 GAP 快 3% 判为负分割，1% 判为匀速；61 分钟、decoupling 6% 判为 watch。`[report]` 改阈值后结论随之改变。
- 合成数据生成器扩展现有的 `tests/synthetic*.py`，不新建平行的一套。
- 前端不加自动测试，和上一阶段一致；最后一个 ticket 由用户在真实数据上目测检查。
- 不在真实数据目录上跑测试，测试一律设 `RUNNING_DATA_DIR` 为临时目录。

## Out of Scope

- 在线地图底图、地名、逆地理编码。
- 用 LLM 生成报告。
- 编辑活动（改名、改类型）、删除活动、在仪表盘里标注比赛。
- 两次活动并排对比；同一路线的历次对比。
- 功率分析（`records.power` 大多为空）。
- 详情或报告的缓存和落库。
- 导出报告（PDF、图片）。

## Further Notes

- **隐私**：路线接口只返回归一化形状。按 `CLAUDE.md`，实施和检查时不在聊天、日志、commit、ticket 里写任何真实坐标、网格点或地名；用真实数据检查时只报汇总数字和"路线显示正常/异常"。
- **心率区间的来源**：Friel 的跑步 LTHR 区间按 Joe Friel 的公开资料，写代码前核对原始出处的边界（Z1 < 85% 等），有出入时以出处为准并在 ticket 里记下。
- **训练类型规则是自定的**，不是来自文献。阈值放在配置里，最后一个 ticket 用真实数据检查后可能要调一次。
- 用户确认方案的时间：2026-11-04。

## 实施时的偏离（已接受）

- 报告条目除 `rule`、`verdict`、`text`、`params` 外还带中文 `name`；`rule` 用英文 id：`training_type`、`aerobic`、`drift`、`pacing`、`load`、`heat`。
- 气温条目在低于阈值时也出现，verdict 为 neutral；只有没有气温数据时不出现。
- 报告在各区块（`SECTIONS`）之后计算，以 `report: {items, method}` 返回。
- `route_unavailable` 是详情的顶层键，不放在 `route` 里面。
- 非跑步类活动也给海拔曲线和路线形状。
- 列表的筛选和页码放在 hash 的查询串里，如 `#/runs?type=all&page=2`。
- 降采样：不含暂停的段多于 1500 段时，整条时间轴一起分桶，这时桶可以跨暂停，点数仍 ≤ 1500。
