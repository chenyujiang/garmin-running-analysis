# 有氧能力、训练负荷、成绩预测的算法调研

Type: research
Status: open
Blocked by: none

## Question

三项核心分析各有哪些成熟算法？每种算法需要什么输入、有什么已知局限？

- **有氧能力（同心率下配速）**：Efficiency Factor、aerobic decoupling（Pa:HR）、固定心率区间配速、GAP（坡度校正配速）等。各自如何从逐秒数据流计算。
- **训练负荷**：TRIMP（Banister / Edwards / Lucia）、CTL/ATL/TSB（Banister 冲动-响应模型）、ACWR。需要哪些生理参数（最大心率、静息心率、乳酸阈心率）。
- **比赛成绩预测**：Riegel 公式、Daniels VDOT、基于 VO2max 的方法，以及 Garmin Race Predictor 公开过的原理。需要什么历史成绩或训练数据。
- 对照：Garmin 自带的 Training Load / VO2max / Race Predictor 的计算口径（Firstbeat 公开资料）。
