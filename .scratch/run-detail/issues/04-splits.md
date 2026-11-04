# 04: 分段：圈和每公里

**What to build:** 详情页两张表：手表的圈分段，和按距离切的每公里分段。

**Blocked by:** 02

**Status:** done

来源：[实施 spec](../spec.md)，User Stories 13–14；Implementation Decisions 里的"每公里分段""圈分段"。

- [x] 圈：取 `laps` 表，`avg_cadence` ×2 换成 spm
- [x] 每公里：按 `records.distance` 每满 1000 m 一段，最后不足 1 km 的一段单独列出并标明距离
- [x] 每公里每段：跑步配速（只算跑的秒）、GAP 配速、平均心率、平均 spm、海拔升降
- [x] 非跑步类活动没有每公里分段（null 加原因）；没有圈时圈表为空并说明
- [x] Seam 3 测试：段数、最后一段距离、spm 换算、某段含走路时跑步配速不含走路

## 结论（实施记录）

- 区块 `splits`，builder `_splits` 在 `analysis/src/running/detail.py` 的 ticket 04 块里，登记在 `SECTIONS` 的 ticket 04 槽。返回 `laps[]`、`kilometres[] | null`、`unavailable{字段: 原因}`、`method`。
- `laps[]`：`lap`（从 1 起，`lap_index + 1`）、`distance_m`、`duration_s`、`pace_s_per_km`、`avg_hr_bpm`、`max_hr_bpm`、`avg_cadence_spm`、`elevation_gain_m`、`elevation_loss_m`，按 `lap_index` 排序。
  - **圈时长（自定）**：取 `timer_duration_s`（不含暂停），没有时退回 `elapsed_duration_s`。配速取 `avg_speed_mps`，没有时用距离 ÷ 计时时长。
  - **非跑步类活动的圈（自定）**：圈照样列出，但 `pace_s_per_km` 和 `avg_cadence_spm` 为 null：骑行的 cadence 是 rpm，×2 不是 spm；与 ticket 02 概要同一口径。
  - 没有圈：`laps` 为 `[]`，`unavailable.laps = "手表没有记录圈"`。
- `kilometres[]`：`km`（从 1 起）、`distance_m`、`partial`、`duration_s`、`running_pace_s_per_km`、`gap_pace_s_per_km`、`avg_hr_bpm`、`avg_cadence_spm`、`elevation_gain_m`、`elevation_loss_m`。
  - 逐秒记录用 `aerobic.steady_state`（含 `classify_records` 的跑走分类和 `gap_mps`），不复制公式。
  - **切分（自定）**：一个采样拥有到它为止的那段区间，归入区间起点所在的公里。整公里的 `distance_m` 写名义值 1000，最后一段写 `总距离 − 整公里数 × 1000`，`partial = true`。边界最多差一个采样（3 m/s 时约 1 秒、0.15 m 海拔）。
  - **最后的零头（自定）**：不足 `MIN_LAST_SPLIT_M`（10 m）的零头不列，免得几米的段给出无意义的配速。
  - 跑步配速 = 跑的秒 ÷ 跑的距离；GAP 配速 = 跑的秒 ÷ Σ(GAP 速度 × 秒)，即按时间加权的平均 GAP 速度。平均心率按 `dt_s` 时间加权（暂停不计，复用概要的 `_weighted_mean`）；平均步频只算跑的秒。
  - **海拔升降（自定）**：逐个采样海拔差的正负分别求和，不平滑；真实数据的气压计噪声会让数值略偏大。
  - 非跑步类活动：`kilometres = null`，`unavailable.kilometres = "仅跑步类活动"`。跑步类但没有逐秒距离（跑步机无记录）：`kilometres = null`，原因"没有逐秒距离记录"。
  - `steady_state` 在函数里局部导入，避免改文件顶部的 import 行，与并行 ticket 的改动隔开。
- 前端 `static/run.js` ticket 04 块：`splitsSection`，一个"分段"区块，先"每公里"表后"手表的圈"表；null 显示 `unavailable` 里的原因或"—"。最后一段在公里号后标距离，如"4（0.30 km）"。复用全局表格样式，没有改 `style.css`；模块级辅助函数都带 `split` 前缀，避免与并行 ticket 重名。
- 测试 `analysis/tests/test_detail_splits.py`（Seam 3，8 个），合成圈数据的辅助函数在新文件 `analysis/tests/synthetic_laps.py`（`Lap`、`add_laps`）：3300 m 分成 3 段整公里加 300 m；含 200 m 走路的一公里跑步配速约 333.75 s/km（全段约 467 s）；5% 上坡和下坡的 GAP 配速 256.1 / 437.0 s/km 与海拔升降 50 m；圈的 spm 换算（88 → 176、84.5 → 169）、计时时长和配速；没有圈时为空并说明；2 m 零头不列；骑行的每公里为 null 加原因、圈不给配速和步频；没有逐秒记录的跑步机跑。
