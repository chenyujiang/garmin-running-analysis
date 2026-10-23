# 分析仪表盘的设计

Type: prototype
Status: open
Blocked by: none

## Question

三项核心分析（有氧能力长期趋势、周跑量与训练负荷、比赛成绩预测）在一个本机仪表盘里应该怎么呈现？

- 用 `impeccable` 做设计：信息层级、布局、图表类型、配色和字体、空状态（数据还没同步时）。
- 做一个粗糙的可交互原型（静态数据即可），先看效果再定细节。
- 原型要能回答：Streamlit 这类现成框架能不能达到这个设计，还是需要自己写前端。这一点决定技术栈。

具体指标公式还没定（见 [有氧能力指标的定义](06-aerobic-metric.md)、[训练负荷模型与成绩预测方法](07-load-and-prediction.md)），原型里先用示意数据。

## Comments

- 2026-10-23：要展示的指标已经定下来，见 [有氧能力指标的定义](06-aerobic-metric.md) 和 [训练负荷模型与成绩预测方法](07-load-and-prediction.md)：有氧能力周趋势（附每周平均温度）、EF、decoupling；CTL/ATL/TSB 和"负荷突增"提示；周跑量；各距离成绩预测（含"过期"状态和 Garmin 参照值）。
- 2026-10-23（来自 [项目骨架与依赖](11-project-skeleton.md)）：计算逻辑放在 `analysis/src/running/` 包里，仪表盘直接复用。分析侧用 polars 和 DuckDB，不依赖 pandas；分析库在数据目录的 `running.sqlite`，只读打开。
