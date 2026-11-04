# 02: 详情页骨架：概要和入口链接

**What to build:** `#/run/<id>` 显示单次活动的概要；活动列表、首页长距离表和最近比赛表的行都链接到这里。不存在的 id 给出明确提示。

**Blocked by:** 01

**Status:** done

来源：[实施 spec](../spec.md)，User Stories 6–9；Implementation Decisions 里的 `running/detail.py` 和"非跑步类活动"。

- [x] `running/detail.py`：`activity_detail(activity_id, root)`，先只含概要
- [x] 概要：距离、时长、跑步配速（复用 `runwalk`）、Garmin 平均配速作参照、平均和最大心率、平均 spm、累计爬升、气温（复用 `aerobic.air_temperature`）
- [x] `GET /api/activities/{activity_id}`；不存在时 404，JSON 带中文说明
- [x] 非跑步类活动：跑步专属字段为 null，带原因"仅跑步类活动"
- [x] `static/run.js`：概要区块；列表行、长距离表、最近比赛表（有 `activity_id` 时）加链接
- [x] Seam 3 测试：概要数值；404；非跑步类活动的 null 和原因

## 结论（实施记录）

- 模块 `analysis/src/running/detail.py`：`activity_detail(activity_id, root=None)`，没有这个活动（或没有分析库）时返回 None；接口 `GET /api/activities/{activity_id}` 遇 None 返回 404，`{"detail": "没有编号为 <id> 的活动。"}`。
- 返回 `activity{activity_id, activity_type, activity_name, start_time_local, is_running}` 加每个区块一个键；本 ticket 只有 `summary`。
- **为并行的 03–06 准备的结构**：
  - 后端：每个区块是一个 builder `(DetailInputs) -> dict`，登记在文件末尾的 `SECTIONS` 字典里。字典里给每个后续 ticket 留了一行注释（`# series (ticket 03)` 等），各 ticket 在**自己那行注释的下一行**加条目；函数写在文件中部各自的 `# --- ... (ticket 0N) ---` 块里。注释行把各 ticket 的改动隔开，减少合并冲突。
  - `DetailInputs` 带 `db`、`config`、`activity`（`activities` 整行）、`is_running`，以及按需加载一次的 `records`（`aerobic.load_records` + `runwalk.classify_records`，含 `spm, dt_s, dd_m, running`）。不含 `lat/lon`，路线 ticket 自己查。
  - 前端 `static/run.js`：`runPage(id)` 读一次接口，`RENDERERS` 数组里每项是 `(detail) => Node | null`，同样每个 ticket 一行注释槽（报告 07 在概要之前）；函数写在各自的块里。`fmtDur`、`fmtPace`、`how` 已导出供后续区块复用。
- 概要字段：`distance_m, duration_s, running_pace_s_per_km, garmin_pace_s_per_km, avg_hr_bpm, max_hr_bpm, avg_cadence_spm, elevation_gain_m, air_temperature_c, unavailable{字段: 原因}, method`。
  - 跑步配速和 Garmin 平均配速都来自 `runwalk.running_summaries(activity_ids=[id])`；没有步频数据时照旧回落到 Garmin 总量。
  - **心率（自定）**：平均心率按逐秒记录 `dt_s` 加权（暂停和第一个采样不计），最大心率取逐秒最大值；没有逐秒心率时取 `activities` 表里 Garmin 的值。
  - **步频（自定）**：只算跑的秒（`running` 为真），按 `dt_s` 加权，与跑步配速同一口径；Garmin 的平均步频含走路，不用。
  - 距离、时长、累计爬升取 `activities` 表的 Garmin 值，不从逐秒海拔重算（气压计噪声大）。
  - 气温：`aerobic.air_temperature`，没有天气数据时为 null。
- **非跑步类活动（自定范围）**：`running_pace_s_per_km`、`garmin_pace_s_per_km`、`avg_cadence_spm` 为 null，`unavailable` 里各写"仅跑步类活动"。Garmin 平均配速和步频也算跑步专属：骑行的 cadence 是 rpm，×2 不是 spm；配速对非跑步没有意义。其余字段照常给出。跑步类活动的 `unavailable` 为空字典；字段因缺数据为 null 时（如没有气温）不写原因。
- 前端：`app.js` 的 `#/run/<id>` 换成 `runPage`；404 时显示"找不到这个活动"和接口给的说明，带回到全部活动的链接。概要用 `.stat-line`，null 值显示原因或"—"（灰色）。首页长距离表的日期、最近比赛表里有 `activity_id` 的行的日期链接到详情页（列表行在 ticket 01 已链接）。CSS 在 `style.css` 末尾 run-detail ticket 02 区块。
- 测试 `analysis/tests/test_detail_api.py`（Seam 3，5 个）：带 5 分钟走路的跑步的概要数值（跑步配速约 333 s/km、Garmin 373.1 s/km、平均心率 144、最大 150、步频约 170、爬升、插值气温 12.42 °C）；不存在的 id 404 和中文说明；没有分析库时 404；骑行的三项 null 和原因，其余字段照常；没有逐秒记录的跑步机跑回落到 Garmin 总量和心率。跑步配速和步频允许 ±1：15 秒尾随平滑会把走路开头几秒算作跑（与 ticket 01 同一个算例）。
