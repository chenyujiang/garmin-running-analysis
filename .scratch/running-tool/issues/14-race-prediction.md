# 14: 成绩预测与比赛

**What to build:** 用户在 `races.csv` 里手工维护比赛清单。仪表盘首屏第三栏显示 5K、10K、半马、全马的预测表：VDOT 为主，Riegel 和 Garmin 两列对照，下面写明依据哪场比赛；6 个月内没有比赛时，表格变淡，用红字说明最近一场比赛的日期，并提示更新 `races.csv`。下方有最近比赛表，有氧能力趋势图上用虚线标出比赛。

**Blocked by:** 10（跑和走的分类与周跑量，接到仪表盘跑量栏），12（有氧能力趋势图）

**Status:** ready-for-agent

来源：[实施 spec](../spec.md)，User Stories 43–46、52、57、58；Implementation Decisions 里的"比赛清单"和"成绩预测"。

- [ ] 读取 `races.csv`，字段 `date, activity_id, distance_m, time_s, all_out, note`；文件缺失或格式错误时给出明确提示
- [ ] 取最近 6 个月内最好的一场 `all_out` 比赛算 VDOT，再换算各距离（写代码前先核对 VDOT 表的原始出处）
- [ ] Riegel 作对照：有 2 场以上比赛时拟合个人指数，否则用 1.06
- [ ] 全马按 Vickers 2016 用最近 8 周平均周跑量修正（先核对系数出处）
- [ ] Garmin Race Predictor 取 `garmin_metrics` 里最近的值；没有数据时这一列留空
- [ ] 6 个月内没有比赛时标为过期，不给预测值
- [ ] 预测接口和比赛接口返回数值、依据、过期标志，以及公式说明和参数
- [ ] 公式级测试：VDOT 换算、Riegel、Vickers 修正，数值与原始出处核对
- [ ] Seam 3 测试：6 个月内没有比赛时返回过期；只有 1 场比赛时 Riegel 用 1.06；`races.csv` 缺失时给出提示
