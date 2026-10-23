# 有氧能力、训练负荷、成绩预测的算法调研

Type: research
Status: resolved
Blocked by: none

## Question

三项核心分析各有哪些成熟算法？每种算法需要什么输入、有什么已知局限？

- **有氧能力（同心率下配速）**：Efficiency Factor、aerobic decoupling（Pa:HR）、固定心率区间配速、GAP（坡度校正配速）等。各自如何从逐秒数据流计算。
- **训练负荷**：TRIMP（Banister / Edwards / Lucia）、CTL/ATL/TSB（Banister 冲动-响应模型）、ACWR。需要哪些生理参数（最大心率、静息心率、乳酸阈心率）。
- **比赛成绩预测**：Riegel 公式、Daniels VDOT、基于 VO2max 的方法，以及 Garmin Race Predictor 公开过的原理。需要什么历史成绩或训练数据。
- 对照：Garmin 自带的 Training Load / VO2max / Race Predictor 的计算口径（Firstbeat 公开资料）。

## Answer

完整调研报告（含来源编号和核实程度）只以文本形式交回到 charting session，尚未写入 `research/analysis-methods` 分支，见 Comments。结论摘要：

- **有氧能力**：主指标用"同心率 GAP 配速"，即每次稳态跑拟合 `speed~HR`，取固定参考心率处的预测 GAP 速度，按周取中位数。辅助指标：EF（GAP 速度 ÷ 心率，只用稳态段），以及 aerobic decoupling（≥60 分钟稳态跑，≤5% 为好）。坡度校正先用 Minetti 2002 的 `Cr(i)` 多项式。三个指标都受温度和心率漂移影响，需要按天气分层。
- **训练负荷**：单次负荷用逐秒累加的 Banister TRIMP（只需 HRmax、HRrest、性别，5 年数据都能回算）。趋势用 CTL(42)/ATL(7)/TSB 的 EWMA，只是相对指标。不拟合完整的 Banister 表现模型，因为比赛点太少，参数病态（Hellard 2006）。ACWR 只当"负荷突增"提示，与受伤没有因果证据（Impellizzeri 2020）。
- **成绩预测**：主方法用 Daniels VDOT，对照用 Riegel `T2=T1(D2/D1)^1.06`，有 ≥2 场成绩时拟合个人指数。两者都会低估全马用时（Vickers 2016，n=2303），要加周跑量修正，并用历史全马回测。
- **Garmin/Firstbeat 口径**：VO2max 基于心率–速度分段，对 HRmax 敏感（偏差 15 bpm 时误差约 7–9%）。Training Load 基于 EPOC，慢性负荷的窗口未公开。Race Predictor = VO2max + 训练史，权重未公开。
- **用户需提供**：实测 HRmax（不用 220−age）、HRrest（Garmin 每日数据即可）、LTHR（Friel 30 分钟测试或历史全力赛）、手工标注的比赛清单（日期、距离、用时、是否全力、天气）、性别；可选参考心率。
- **未读到原文的来源**：TrainingPeaks 帮助中心、Strava GAP 博客、Riegel 原文、Daniels 和 Edwards 的书、Banister TRIMP 系数原文。写代码前要再核对相关公式。

## Comments

- 2026-10-23：research subagent 尝试把报告写入文件时被 harness 拦截（"Subagents should return findings as text, not write report files"），所以分支 `research/analysis-methods` 目前是空的。报告全文保留在 charting session 的对话里。
