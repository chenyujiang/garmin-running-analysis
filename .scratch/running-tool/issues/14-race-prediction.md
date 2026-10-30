# 14: 成绩预测与比赛

**What to build:** 用户在 `races.csv` 里手工维护比赛清单。仪表盘首屏第三栏显示 5K、10K、半马、全马的预测表：VDOT 为主，Riegel 和 Garmin 两列对照，下面写明依据哪场比赛；6 个月内没有比赛时，表格变淡，用红字说明最近一场比赛的日期，并提示更新 `races.csv`。下方有最近比赛表，有氧能力趋势图上用虚线标出比赛。

**Blocked by:** 10（跑和走的分类与周跑量，接到仪表盘跑量栏），12（有氧能力趋势图）

**Status:** done

来源：[实施 spec](../spec.md)，User Stories 43–46、52、57、58；Implementation Decisions 里的"比赛清单"和"成绩预测"。

- [x] 读取 `races.csv`，字段 `date, activity_id, distance_m, time_s, all_out, note`；文件缺失或格式错误时给出明确提示
- [x] 取最近 6 个月内最好的一场 `all_out` 比赛算 VDOT，再换算各距离（写代码前先核对 VDOT 表的原始出处）
- [x] Riegel 作对照：有 2 场以上比赛时拟合个人指数，否则用 1.06
- [x] 全马按 Vickers 2016 用最近 8 周平均周跑量修正（先核对系数出处）
- [x] Garmin Race Predictor 取 `garmin_metrics` 里最近的值；没有数据时这一列留空
- [x] 6 个月内没有比赛时标为过期，不给预测值
- [x] 预测接口和比赛接口返回数值、依据、过期标志，以及公式说明和参数
- [x] 公式级测试：VDOT 换算、Riegel、Vickers 修正，数值与原始出处核对
- [x] Seam 3 测试：6 个月内没有比赛时返回过期；只有 1 场比赛时 Riegel 用 1.06；`races.csv` 缺失时给出提示

## 结论

- **用户决定（覆盖上面"全马按 Vickers 修正 VDOT"的写法）**：5K、10K、半马的主预测用 VDOT；全马的主预测用 Riegel 加 Vickers & Vertosick 2016 的修正（Model 1 修正速度，Model 2 修正指数），不把系数套在 VDOT 上。原因是论文只有基于 Riegel 的版本。出处：*BMC Sports Sci Med Rehabil* 2016;8:26，PMC5000509，系数在 Additional file 1（docx）。核对过程和测试向量见 `running-tool-notes/formulas.md` §4。
- 周跑量：截至今天的 56 天内 `running_summaries.run_distance_m` 之和 ÷ 8，再按论文用法换成英里（÷ 1.609344）。论文用的是自报的"典型周跑量"，8 周平均是我们的口径。
- Vickers 的输入只取非全马的全力比赛（距离 < 0.95 × 全马）：以 VDOT 最高的一场为准；另有一场与它距离相差 ≥ 1.5 倍时，取其中 VDOT 最高的一场用 Model 2，否则用 Model 1。窗口内没有非全马比赛时，全马退回 VDOT。
- 没做论文的比赛难度调整（`races.csv` 没有难度列），一律按普通难度。
- 依据比赛 = 6 个日历月窗口（含边界当天）内 VDOT 最高的全力比赛；今天以后的比赛不计。
- Riegel 个人指数：窗口内所有全力比赛做 log-log 最小二乘，截断到 [1.01, 1.20]；距离少于 2 种时用 1.06。
- Garmin 列取今天及以前、预测字段非空的最近一行；`garmin_metrics` 表（ticket 06）还没合并时按无数据处理。过期时 Garmin 列照样显示。
- 接口：`GET /api/predictions`、`GET /api/races`，都支持 `?today=`。前端：首屏第三栏 `predictions.js`，下方第二栏 `races.js`（非全力的比赛灰显），有氧趋势图在比赛所在周画红色虚线。
- 测试：`tests/test_prediction_formulas.py`（公式级，25 个）、`tests/test_predictions_api.py`（Seam 3，15 个）。
