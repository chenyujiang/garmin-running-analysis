# 07: 分析报告（固定规则）

**What to build:** 详情页最上面一段中文分析报告：训练类型、有氧能力对比、心率漂移、配速分布、负荷、气温。每条带规则名、结论级别、实际数值和阈值；阈值在 `config.toml` 里可调。

**Blocked by:** 03、04、06

**Status:** done

来源：[实施 spec](../spec.md)，User Stories 21–30；Implementation Decisions 里的"分析报告"。

- [x] `running/report.py`：纯函数 `run_report(detail, context)`，每条含 `rule, verdict, text, params`，`verdict` 为 `good`、`neutral`、`watch`、`unknown`
- [x] 六条规则按 spec 实现：训练类型、有氧能力对比、心率漂移、配速分布、负荷、气温
- [x] 新配置 `[report]`，默认值见 spec；气温阈值沿用 `[aerobic].hot_week_c`
- [x] 判断不了的规则说明原因（没有心率、没有 GPS、太短、非跑步类）
- [x] 报告并入 `GET /api/activities/{activity_id}` 的返回
- [x] 前端：每条一行，结论在前，规则和数值可展开；watch 用红色 `#b0281f`
- [x] Seam 3 测试：每条规则命中和不命中各一个合成活动；改 `[report]` 阈值后结论随之改变

## 结论（实施记录）

- 模块 `analysis/src/running/report.py`：`report_context(d, detail)` 读库（逐秒稳态帧、4 周基线、当周 TRIMP 和 TSB），`run_report(detail, context) -> Report` 是纯函数。返回 `report: {items[], method{name, description, params}}`；每条 `rule, name, verdict, text, params`。`rule` 用英文 id（`training_type`、`aerobic`、`drift`、`pacing`、`load`、`heat`），另加中文 `name` 供前端显示（spec 只列了四个字段，`name` 是自加的）。
- 报告不进 `SECTIONS`：它要读其他区块的输出（`summary`、`metrics`），所以在 `detail.py` 的 `activity_detail` 里最后算，挂在 `detail["report"]`。
- 配置 `config.py` 新增 `Report` dataclass 和 `[report]` 段，9 个默认值同 spec。
- **训练类型（自定细节）**：
  - "30 秒平滑速度"复用 `[aerobic].smoothing_s`（30 s）和 `aerobic.steady_state` 算出的 `speed_smooth`。中位速度只算"在跑"的秒。
  - 间歇的"段间有恢复"：两段快跑之间的平滑速度要跌到中位速度以下才算两段，否则合成一段。暂停（`dt_s = 0`）打断一段。
  - 区间占比只算在跑、有心率的秒，用原始心率；"连续 15 分钟"用平滑心率判断，避免单秒抖动打断。
  - 没有区间（没有心率或 LTHR）且不是间歇时为 unknown，并说明原因；间歇判断不需要心率。
  - 训练类型本身没有好坏，verdict 一律 neutral。
- **有氧能力对比（自定细节）**：基线 = 本次所在周的周一之前 `rolling_weeks`（4）周里，每周有效跑 ≥ `min_runs_per_week`（2）次的周中位数，再取中位数。和趋势图的滚动值不同，这里不要求紧挨的上一周本身有值。没有基线时为 unknown；本次不计入有氧能力时沿用 ticket 06 `metrics.unavailable.aerobic` 的原因。
- **心率漂移**：直接用 ticket 06 的 `metrics.ef`，60 分钟和 5% 沿用 `longruns.MIN_DURATION_S`、`DECOUPLING_LIMIT_PCT`，不放进 `[report]`。不足 60 分钟为 neutral，只给 EF。
- **配速分布（自定细节）**：跑的秒按累计距离对半分，比较两半的时间加权 GAP 配速。负分割和匀速都是 good，正分割是 watch。间歇跑不判（unknown）。
- **负荷（自定细节）**：复用 `load._activity_trimp` 和 `load._series`。"跑前 TSB"取当天的点，"第二天 TSB"取次日的点；ATL/CTL 用当天的点，> `load.SPIKE_RATIO`（1.5）为 watch，否则 neutral。当周按周一到周日。
- **气温**：≥ `hot_week_c` 为 watch，低于时也出一条 neutral（spec 只说了 watch 和没有数据不出现）。
- 前端 `static/run.js` 的 `reportSection`（ticket 07 槽，放在概要之前）：每条一行 `<details>`，摘要行是"结论、规则名、一句话"，展开后显示规则 id 和 `params` 表；"怎么算的"显示 `method.description`。CSS 在 `style.css` 末尾 ticket 07 区块，只有 watch 用红色，unknown 用浅灰。
- 测试 `analysis/tests/test_detail_report.py`（Seam 3，31 个）：间歇 3 段命中、2 段不命中，`interval_min_reps = 4` 后 3 段也不命中；节奏跑 20 分钟连续命中、分段不命中，`tempo_min_s = 480` 后命中；长距离、轻松、混合；没有心率时 unknown；有氧能力好、持平、留意三档，`aerobic_change = 0.05` 后变持平，没有基线和不计入时 unknown；漂移 > 5% watch、0% good、不足 60 分钟 neutral；配速负分割、匀速、正分割，`split_change = 0.04` 后变匀速，间歇不判；负荷首次一小时突增 watch、每天同量 neutral；气温 25 °C watch、15 °C neutral，`hot_week_c = 14` 后 watch，没有气温时不出现；骑车只给负荷。
