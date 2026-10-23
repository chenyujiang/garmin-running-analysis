# 有氧能力、训练负荷、成绩预测的算法调研

对应 ticket：`.scratch/running-analysis/issues/02-analysis-methods.md`
调研日期：2026-10-23

数据前提：Garmin FIT 逐秒数据流（心率、速度/配速、步频、GPS、海拔），约 5 年历史。主模型自己算，Garmin/Firstbeat 指标只作参照。

## 怎么读这份文档

- 每条结论后面的 `[Sx]` 是来源编号，完整列表见文末「来源」。
- **核实程度**：标「已核实」的，表示我读过原文或官方页面。标「未读原文」的，表示原文拿不到（付费墙、书籍、站点 403），只能依据摘要、引用它的论文或广泛复现的公式。写代码前应再核对一遍。
- 术语沿用根目录 `GLOSSARY.md`：**有氧能力** = 相同心率下的配速，不等于 VO2max。

---

## 1. 有氧能力（同心率下配速）

### 1.1 Efficiency Factor（EF）

- **定义**：输出 ÷ 平均心率。骑行用 `NP / avg HR`；跑步先把 Normalized Graded Pace（NGP）换成速度（NGS），再用 `NGS / avg HR`。EF 上升说明每次心跳产出的速度更高，即有氧能力提高。[S1，已核实]
- **单位**：TrainingPeaks 页面没写跑步 EF 的单位 [S1]。自己实现时建议固定用 `m/min ÷ bpm`（即每次心跳前进多少米），跨时间可比就行。
- **输入**：速度流和心率流。用 NGP/GAP 时还要海拔流。不需要任何生理参数。
- **从逐秒数据流计算**：
  1. 去掉暂停段、速度 < 某阈值（如 1.5 m/s）的点，以及开头热身段（如前 10 分钟，心率还在爬升）。
  2. 用坡度校正后的速度（见 1.3 GAP）代替原始速度。
  3. `EF = mean(gap_speed_m_per_min) / mean(hr)`，只在"稳态有氧"段上算。
- **使用条件**：只有条件相近的训练之间才能比较 EF。要控制的因素：赛前疲劳、装备、路线、天气、海拔、赛前饮食（尤其咖啡因）、热身和时段。[S1，已核实]
- **局限**：
  - 心率受温度、脱水、疲劳影响：长时间运动中心率会漂移，每搏量下降 [S20，已核实（摘要）]。夏天的 EF 会系统性偏低。
  - 跑步经济性本身也会影响同速度下的耗氧量 [S21，已核实（摘要）]。所以 EF 反映的是"心肺能力 × 跑步经济性"的合成结果，跟 GLOSSARY 里"有氧能力"的定义正好一致。
  - 间歇课或变速跑的平均心率滞后于速度，EF 没有意义。

### 1.2 Aerobic decoupling（Pa:HR，有氧解耦）

- **定义**：把一次训练（或一段）分成前后两半，分别算 EF，`decoupling = (EF_1st − EF_2nd) / EF_1st × 100%`。[S1，已核实]
- **阈值**：稳态有氧训练解耦 ≤ 5% 表示有氧耐力良好，> 5% 说明还需要更多有氧训练。负值常见于热身不足或天气变化，通常视为正常。[S1，已核实]
- **"Pa:HR" 这个名字**：TrainingPeaks 的 EF 页面没出现这个名字 [S1]。它是 TrainingPeaks 软件和 Friel 著作里的叫法，指 pace 对 HR 的比值。计算方法同上。
- **输入**：同 EF。
- **从逐秒数据流计算**：取稳态主体段（去掉热身/放松），按**时间**对半分。分别算 GAP 速度均值 / 心率均值，再按公式求解耦。
- **前提**：全程有氧（低于乳酸阈）、配速稳定（变异指数低）[S1，已核实]。按经验至少要 60 分钟以上才看得出漂移（这是经验值，没有一手来源）。
- **局限**：它衡量的是**耐久性**（心率漂移），不直接衡量同心率配速的水平。高温和脱水会放大解耦 [S20]，所以和 EF 一样需要做天气分层。

### 1.3 GAP / NGP（坡度校正配速）

**Minetti 能量消耗曲线（物理基础）**

- Minetti 等 2002 年在跑步机上测量了坡度 −0.45 到 +0.45 的跑步能量消耗 `Cr`（J·kg⁻¹·m⁻¹）。结果：平地约 3.40，与速度无关；+0.45 时 18.93；最低点在 −0.20 附近，为 1.73；坡度更陡时又回升，−0.45 时 3.92。[S2，已核实（摘要）]
- 论文给出的五次多项式拟合（`i` 为坡度，小数）：
  ```
  Cr(i) = 155.4 i^5 − 30.4 i^4 − 43.3 i^3 + 46.3 i^2 + 19.5 i + 3.6
  ```
  [S2，多项式未读原文，按广泛复现的版本记录。注意 `Cr(0)=3.6`，与摘要中实测的 3.40 略有差别，这是拟合值。]
- 用法：`GAP_speed = speed × Cr(i) / Cr(0)`，即把当前坡度的代谢成本折算成等价平地速度。

**Strava GAP**

- Strava 的 GAP 估算的是"同样努力在平地上能跑多快"：上坡时 GAP 比实际配速快，下坡时更慢。根据运动员数据，下坡校正在约 −10% 坡度时达到峰值，之后略微减弱。GAP 不考虑地形技术难度和路面状况。[S3，已核实]
- 2017 年改进版模型用的是大量用户的逐秒数据流。Strava 的专利 US11623121B1 描述：先按**心率**挑选活动片段，再拟合"坡度 → 无量纲配速调整系数"的映射 [S4，已核实（专利摘要）]。Strava Engineering 博客原文（Drew Robb, 2017）返回 403，没读到。
- 结论：Strava 的曲线来自"心率等效"，而 Minetti 曲线来自"耗氧等效"。下坡段两者差别最大：Minetti 认为 −20% 最省力，Strava 认为约 −10% 后收益就递减。

**TrainingPeaks NGP**：TrainingPeaks 用 NGP 计算 rTSS 和跑步 EF，但没有公开具体算法 [S1][S5]。

- **从逐秒数据流计算**：
  1. 海拔：优先用气压计海拔（FIT 的 `enhanced_altitude`）。GPS 海拔噪声大，要先平滑（如 30 s 滚动中位数）。
  2. 坡度：用约 10–30 m 的距离窗口算 `Δalt / Δdist`，并截断在 ±0.45（超出了 Minetti 的测量范围）。
  3. 套用 `Cr(i)/Cr(0)` 或自拟合的调整系数，得到逐秒 GAP 速度。
- **局限**：海拔噪声会被放大成坡度噪声；不考虑技术地形和路面 [S3]；跑步机活动没有坡度数据，坡度要按手动设置处理。

### 1.4 固定心率区间配速 / 同心率配速回归

- **思路**：直接按 GLOSSARY 的定义，取每次跑步中心率落在固定窗口（如 140±3 bpm）的稳态点，算 GAP 配速中位数，再画出它随时间的变化。
- **更稳健的版本**：对每次跑步的稳态点拟合 `speed = a + b × HR`，再在参考心率（如 145 bpm）处求预测速度。Firstbeat 的 VO2max 算法也建立在"心率–速度关系"上：先把数据按心率区间分段，评估每段的可靠性，再用最可靠的分段拟合线性或非线性关系 [S6，已核实]。
- **Firstbeat 自动剔除的情况**（可直接借用作清洗规则）：软地面、陡下坡、红绿灯停下（速度为 0 但心率仍高），以及长时间运动的心率漂移 [S6，已核实]。
- **输入**：速度/海拔流、心率流。参考心率要选一个用户常跑的有氧强度。
- **局限**：光电心率在开头几分钟和间歇时误差大。温度影响见 1.1。

---

## 2. 周跑量与训练负荷

周跑量本身就是按周（建议 ISO 周，周一开始）汇总跑步活动的距离，无需专门的算法。下面讨论负荷模型。

### 2.1 TRIMP 系列（心率负荷）

**Banister TRIMP**

- 公式（ΔHRr 为心率储备比例）：
  ```
  ΔHRr  = (HR − HRrest) / (HRmax − HRrest)
  TRIMP = Σ Δt[min] × ΔHRr × 0.64 × e^(1.92 × ΔHRr)   # 男
  TRIMP = Σ Δt[min] × ΔHRr × 0.86 × e^(1.67 × ΔHRr)   # 女
  ```
  来源是 Morton, Fitz-Clarke & Banister 1990 [S7] 和 Banister 1991 年的书章。摘要已核实：模型以量化的训练冲量为输入 [S7]。权重系数未读原文，按广泛复现的版本记录。
- **逐秒计算**：`Δt = 1/60` 分钟，逐点累加。原文的形式是"平均心率 × 时长"，逐秒累加更精确。指数项是凸函数，所以两种算法在间歇课上结果会不一样。
- **输入**：HRmax、HRrest、性别。
- **局限**：指数权重来自血乳酸的群体曲线，不是个体曲线。HRmax 设错会直接放大误差。

**Edwards TRIMP（分区法）**

- 按 %HRmax 分五区：50–60% ×1，60–70% ×2，70–80% ×3，80–90% ×4，90–100% ×5，再乘以各区分钟数求和。出处是 Edwards 1993 的书《The Heart Rate Monitor Book》[S8，书籍，未读原文]。
- **输入**：HRmax。**局限**：区间边界处负荷会跳变；50% HRmax 以下不计负荷。

**Lucia TRIMP（个体化三区）**

- 按通气阈 VT 和呼吸补偿点 RCP 把强度分成三区（<VT，VT–RCP，>RCP），每区分钟数乘以该区系数后求和 [S9，已核实（摘要）]。系数为 1/2/3（摘要没写，按原文的广泛引用记录）。
- **输入**：VT1/VT2 对应的心率，需要实验室测试或可靠的场地估计（例如用 LTHR 近似 VT2）。

**session-RPE**（Foster 2001）：负荷 = 主观用力度 RPE × 时长（分钟）。在稳态和间歇骑行中都与心率法高度一致 [S10，已核实（摘要）]。Garmin 不记录 RPE，作为备选。

### 2.2 TSS 系列（TrainingPeaks）

- **TSS**：`TSS = (sec × NP × IF) / (FTP × 3600) × 100`，其中 `IF = NP / FTP`，所以 `TSS = 小时数 × IF² × 100`。按定义，在阈值强度跑 1 小时 = 100 TSS。[S5，已核实]
- **rTSS**：跑步版，用 NGP 对比"功能阈值配速"（FTPa，即能维持 1 小时的最快配速）。坡度越大，同配速得分越高 [S11，已核实]。可以类比为 `IF = NGS / threshold_speed`，代入上面的式子（这是类比推导，TrainingPeaks 没有逐字公开 rTSS 公式）。
- **hrTSS**：基于用 LTHR 划分的心率区间的停留时间。在没有功率/配速数据时作为后备。对短间歇不准，因为心率反应滞后 [S12，Suunto 的转述；TrainingPeaks 帮助中心 403，未读原文]。
- **LTHR 场地测试（Friel）**：独自跑 30 分钟计时跑，均匀配速，第 10 分钟按圈，取最后 20 分钟的平均心率作为 LTHR。跑步心率区间（%LTHR）：Z1 <85，Z2 85–89，Z3 90–94，Z4 95–99，Z5a 100–102，Z5b 103–106，Z5c >106。[S13，已核实]

### 2.3 Banister 冲动–响应模型与 CTL/ATL/TSB

**原始模型**（Banister；Morton 1990）

- 训练冲量 `w(s)` 同时产生"体能"和"疲劳"两个响应。没有训练时两者都按指数衰减，表现 = 两者的线性组合 [S7，已核实（摘要）]：
  ```
  p(t) = p0 + k1 Σ_{s<t} w(s) e^{-(t-s)/τ1} − k2 Σ_{s<t} w(s) e^{-(t-s)/τ2}
  ```
- 参数 `k1, k2, τ1, τ2` 需要用个体的成绩序列拟合 [S7]。
- **局限**：Hellard 2006 对精英游泳运动员拟合后发现 R² = 0.79±0.13，但参数置信区间很宽：τ_体能 = 38 天（95% CI 17–59），τ_疲劳 = 19 天（6–32）。部分参数高度相关，导致参数"无法解释"（病态问题）[S14，已核实（摘要）]。
- **对本项目的影响**：用户一年只有几场比赛，"成绩"数据点太少，不足以稳定拟合 4 个参数。可以考虑用 1.4 节的同心率配速作为高频的表现代理变量，但这条路线没有文献验证。

**Performance Manager（CTL/ATL/TSB，Coggan）**

- CTL 和 ATL 都是每日 TSS 的**指数加权移动平均**，默认时间常数分别为 42 天和 7 天。`TSB = CTL − ATL` [S15，已核实]。TrainingPeaks 定义 Form 时用的是**昨天**的 CTL − ATL [S16，已核实]。
- 它和 Banister 模型的关系：去掉增益 `k1/k2`，把积分换成移动平均。所以 CTL/ATL 只是相对指标，不是表现预测 [S15，已核实]。
- **渐进速率**：CTL 连续 4 周以上每周增加 >5–7 TSS/d，常导致生病或过度训练 [S15，已核实]。
- **TSB 区间**：比赛日 Form 建议在略负到约 +25 之间，且因人而异 [S16，已核实]。
- **实现**：TrainingPeaks 页面没给递推式 [S15]。常见的 EWMA 实现如下，两种写法在 TC=42 时差别很小：
  ```
  CTL_t = CTL_{t-1} + (TSS_t − CTL_{t-1}) × (1 − e^{-1/42})
  # 近似写法：× 1/42
  ```
- **输入**：每日负荷（TSS/rTSS/hrTSS/TRIMP 都可以），时间常数 42/7。没有训练的日子记 0，不能跳过。

### 2.4 ACWR（急慢性负荷比）

- **定义**：Hulin 2016 年用 1 周负荷总和作为急性负荷，过去 4 周急性负荷的平均作为慢性负荷，两者相除。在橄榄球联盟运动员中，ACWR ≥ 2.11 时当周受伤风险最高（16.7%）。慢性负荷高、比值适中（1.02–1.18）时风险更低 [S17，已核实（摘要）]。
- **EWMA 版**：Williams 2017 年提出用指数加权平均代替滚动平均 [S18，已核实（题录）]。
- **Garmin 的 Load Ratio**：急性负荷 ÷ 慢性负荷。<0.8 低，0.8–1.4 最佳，1.5–1.9 高，≥2.0 很高。训练满 2 周后才显示 [S19，已核实]。
- **局限**：Impellizzeri 2020 指出，从没有研究正确估计过 ACWR 对受伤的因果效应。比值数据本身也有问题：分子没有被分母真正归一化 [S22，已核实（摘要）]。滚动版还存在数学耦合，即急性负荷包含在慢性负荷里 [S23，已核实（摘要）]。证据来自团队运动，迁移到个人跑步的证据有限。**建议只把它当成"负荷突增"的提示，不当成受伤预测。**

---

## 3. 比赛成绩预测

### 3.1 Riegel 公式

- `T2 = T1 × (D2 / D1)^1.06`。来源：Riegel, *American Scientist* 69(3):285–290, 1981 [S24，题录已核实，原文 PDF 证书错误，未读]。原文适用范围约 3.5–230 分钟 [S24，二手转述]。
- **指数的取值不统一**：Vickers & Vertosick 2016 按 Riegel 引用 `k = 1.07` [S25，已核实]。
- **局限**：在 2303 名业余跑者中，Riegel 公式到半马为止校准良好，但**严重低估全马用时**：一半跑者的预测快了 10 分钟以上。基于 1 场或 2 场既往比赛加训练量的模型，把 MSE 从 381 降到 228 和 208 [S25，已核实]。
- **个体化**：有两个以上不同距离的全力成绩时，可以拟合自己的指数 `k = ln(T2/T1) / ln(D2/D1)`。
- **输入**：至少一场近期全力比赛（或计时跑）的距离和成绩。

### 3.2 Daniels VDOT

- **公式**（Daniels & Gilbert 1979，*Oxygen Power*）：`v` 为平均速度（m/min），`t` 为用时（min）。
  ```
  VO2(v)   = −4.60 + 0.182258 v + 0.000104 v²
  %max(t)  = 0.8 + 0.1894393 e^(−0.012778 t) + 0.2989558 e^(−0.1932605 t)
  VDOT     = VO2(v) / %max(t)
  ```
  [S26，书籍，未读原文。公式按多个计算器的复现记录。] 自检：5K 用时 20:00 → v=250 → VO2≈47.5，%max≈0.953 → VDOT≈49.8。这与 Firstbeat 白皮书转载的 Daniels 表（VO2max 48 → 5K 20:39）同一量级 [S6]。
- **预测**：已知 VDOT 时，对目标距离 D 解方程 `VO2(D/t) / %max(t) = VDOT` 求 t（单调，用二分法或牛顿法即可）。
- **VDOT 不是实测 VO2max**：它是由成绩反推的"伪 VO2max"，同时包含了跑步经济性 [S26]。Firstbeat 也指出：精英运动员之间 VO2max 差距小，成绩更多取决于其他因素 [S6，已核实]。
- **局限**：假设对各距离都有相应训练。低跑量跑者用短距离成绩预测全马会偏乐观，与 Riegel 的问题同源 [S25]。
- **输入**：一场近期全力成绩。

### 3.3 基于 VO2max（或自算"有氧指数"）的方法

- **Firstbeat 的方法**：先估 VO2max，再查 Daniels 表得到各距离预测成绩（白皮书 Table 4 直接给出了 VO2max 30–84 对应的马拉松到 1 英里成绩）[S6，已核实]。
- **自建方案**：用 3.2 节的 `VO2(v)` 把稳态段速度换算成耗氧，结合 `%HRR` 或 `%HRmax` 拟合"心率–VO2"线，外推到 HRmax，得到"训练中的 VDOT"。这样有氧能力（第 1 节）和成绩预测（3.2 节）就用同一套单位。这是本文推导的组合思路，没有文献直接验证，需要拿用户的真实比赛成绩来回测。

---

## 4. Garmin / Firstbeat 指标的计算口径（作参照）

### 4.1 VO2max

- **方法**：Firstbeat 的步骤如下 [S6，已核实]：
  1. 至少输入年龄；
  2. 记录心率和速度；
  3. 把数据按心率区间分段，评估每段的可靠性；
  4. 用最可靠的分段，按心率–速度的线性或非线性关系估算 VO2max。
- **精度**：在 79 名跑者的 2690 次自由跑中，MAPE 约 5%，多数误差 < 3.5 ml/kg/min。75% 的训练在跑满 2 km 后就能得到估计 [S6]。
- **对 HRmax 敏感**：方法默认用按年龄估的 HRmax。HRmax 低估 15 bpm 时误差约 9%，高估 15 bpm 时约 7%；用真实 HRmax 时降到约 5% [S6，已核实]。
- **环境影响**：跑步路面、风、高海拔会影响速度。在非标准条件下，结果反映的是"该条件下的表现" [S6，已核实]。
- **Garmin 的使用条件**：需要腕部或胸带心率；户外 GPS 跑步，≥70% HRmax 至少 10 分钟；建议设置真实 HRmax。数据由 Firstbeat Analytics 提供，分级采用 Cooper Institute 标准 [S27，已核实]。

### 4.2 Training Load / Acute Load / Load Ratio

- **EPOC 模型**：`EPOC(t) = f(EPOC(t−1), exercise_intensity(t), t)`（Saalasti 2003）。强度用 %VO2max 表示，由心率换算 [S28，已核实]。具体规律：
  - <30–40% VO2max 时，开头的上升之后基本不再累积；>50% 时持续累积，强度越高斜率越大；
  - 高强度累积、低强度回落，结果由"上坡公式"和"下坡公式"组合而成。
- **EPOC 验证**：与实测 EPOC 的 r² = 0.79，合并 MAE 为 13.7 ml/kg [S28，已核实]。
- **模型来源**：基于 48 种运动设置、158 名受试者的荟萃数据 [S28]。
- **Training Effect**：由单次训练的 EPOC 峰值和个人活动等级共同决定 [S29，已核实]。设置的 HRmax 过低会高估 TE，过高会低估 TE [S29]。
- **Garmin 旧版 Training Load** = 过去 7 天 EPOC 之和 [S30，已核实]。
- **新版 Acute Load** = 过去若干天 EPOC 的**加权**和。最佳区间按个人体能和训练史调整 [S19，已核实]。
- **Load Ratio** = 急性 ÷ 慢性，区间见 2.4 节 [S19]。
- 慢性负荷的窗口、权重衰减常数：Garmin 和 Firstbeat **都未公开**。社区 wiki 称每次活动的负荷约 10 天衰减完，并归一到 7 天 [S31，社区来源，未核实]。
- **Training Load Focus**：把 4 周负荷分成 low aerobic / high aerobic / anaerobic 三类，并给出目标 [S19，已核实]。

### 4.3 Race Predictor

- **Garmin 官方说法**：用 VO2max 估计值加训练史给出目标成绩，分析数周训练数据来细化预测。刚开始可能不准；建议完善个人资料并设置 HRmax [S32，已核实]。
- **Firstbeat 白皮书**：以 Daniels 表作为 VO2max → 成绩的示例 [S6]。
- **新旧版差异**：社区和评测称旧版设备只用 VO2max（同 VO2max 的人预测相同）。新版设备加入了训练量，跑量不足时会调慢半马和全马的预测 [S33，二手来源]。具体权重**未公开**。

---

## 5. 推荐清单

### 目标 1：有氧能力

1. **主指标：同心率 GAP 配速**（1.4 节回归版）。每次稳态跑拟合 `speed~HR`，在固定参考心率处取预测 GAP 速度，按周取中位数画趋势。理由：与 GLOSSARY 定义一一对应；Firstbeat 用的是同一物理基础 [S6]。
2. **辅助：EF**（GAP 速度 / 心率，只用稳态段）[S1]。
3. **辅助：Aerobic decoupling**，只对 ≥60 分钟的稳态跑计算，用来看耐久性 [S1]。
4. **GAP 先用 Minetti 多项式** [S2]，以后可以用自己的数据拟合"心率等效"曲线（Strava 思路 [S4]）。
5. 每个指标都附上当天温度，用于分层或回归校正 [S20]。Garmin VO2max 只作对照曲线。

### 目标 2：周跑量与训练负荷

1. **周跑量**：按 ISO 周汇总距离（无模型）。
2. **单次负荷：Banister TRIMP**（逐秒累加）[S7]。理由：只要心率和两个生理参数，5 年数据都能回算。配速可靠时并行算 rTSS 类指标（GAP 速度 / 阈值速度）[S5][S11] 做交叉验证。
3. **趋势：CTL(42) / ATL(7) / TSB** [S15][S16]。时间常数先用默认值，不要尝试拟合完整的 Banister 表现模型（数据点不足，参数病态 [S14]）。
4. **ACWR / Load Ratio**：只作负荷突增提示（>1.5），不解读为受伤风险 [S22]。
5. Garmin Acute Load 只作对照。

### 目标 3：比赛成绩预测

1. **主方法：Daniels VDOT** [S26]。用最近 6–12 个月的全力成绩算 VDOT，再预测其他距离。
2. **对照：Riegel**，有两个以上距离的成绩时拟合个人指数 [S24][S25]。
3. **全马要校正**：VDOT 和 Riegel 都容易偏快 [S25]。建议用 Vickers 的思路，把近 8–12 周的周跑量作为修正项，并用自己的历史全马回测。
4. **进阶**：用目标 1 的同心率配速 / "训练 VDOT"（3.3 节）补全两场比赛之间的空档，需要回测验证。
5. Garmin Race Predictor 只作对照。

### 用户需要提供的输入

| 输入 | 用途 | 来源建议 |
|---|---|---|
| **HRmax**（实测） | TRIMP、%HRmax 分区、VO2max 外推、校准 Garmin | 5 年数据里比赛/冲刺的最高可信心率（排除光电心率尖峰），或场地测试。不要用 `220−age`；不得已时用 Tanaka `208 − 0.7×age` [S34] |
| **HRrest** | Banister TRIMP（心率储备） | Garmin 每日静息心率（已在同步范围内），取滚动中位数 |
| **LTHR** | hrTSS、心率分区、近似 Lucia 的 VT2 | Friel 30 分钟测试 [S13]，或从历史 30–60 分钟全力比赛中提取 |
| **阈值配速**（FTPa） | rTSS 类负荷 | 1 小时全力配速，可由 VDOT 推算 |
| **比赛成绩清单**（日期、距离、用时、是否全力、赛道海拔/天气） | VDOT、Riegel、回测 | 用户手工标注：Garmin 活动没有可靠的"比赛"标记 |
| **性别** | Banister TRIMP 系数 | 账户资料 |
| **（可选）参考心率** | 同心率配速指标 | 选一个用户常跑的有氧心率，如 HRmax 的 75% |
| **（可选）VT1/VT2 实验室数据** | Lucia TRIMP | 有就用，没有就跳过 |

---

## 来源

- [S1] TrainingPeaks, "Efficiency Factor and Decoupling". https://www.trainingpeaks.com/learn/articles/efficiency-factor-and-decoupling/
- [S2] Minetti AE, Moia C, Roi GS, Susta D, Ferretti G. Energy cost of walking and running at extreme uphill and downhill slopes. *J Appl Physiol* 2002;93:1039–1046. PMID 12183501.
- [S3] Strava Support, "Grade Adjusted Pace (GAP)". https://support.strava.com/hc/en-us/articles/216917067-Grade-Adjusted-Pace-GAP
- [S4] Strava, US Patent US11623121B1, "Using aggregate activity data to generate a grade adjusted pace model". https://patents.google.com/patent/US11623121 ；博客 Robb D., "An Improved GAP Model", Strava Engineering, 2017（403，未读）。
- [S5] TrainingPeaks, "Estimating Training Stress Score (TSS)". https://www.trainingpeaks.com/learn/articles/estimating-training-stress-score-tss/
- [S6] Firstbeat Technologies, "Automated Fitness Level (VO2max) Estimation with Heart Rate and Speed Data", white paper, 2014, updated 2017-06-30. https://www.firstbeat.com/wp-content/uploads/2017/06/white_paper_VO2max_30.6.2017.pdf
- [S7] Morton RH, Fitz-Clarke JR, Banister EW. Modeling human performance in running. *J Appl Physiol* 1990;69:1171–1177. PMID 2246166.（另：Banister EW. Modeling elite athletic performance. In: *Physiological Testing of Elite Athletes*, 1991，书章，未读。）
- [S8] Edwards S. *The Heart Rate Monitor Book*. 1993.（书籍，未读）
- [S9] Lucia A, Hoyos J, Santalla A, Earnest C, Chicharro JL. Tour de France versus Vuelta a España: which is harder? *Med Sci Sports Exerc* 2003;35:872–878. PMID 12750600.
- [S10] Foster C, et al. A new approach to monitoring exercise training. *J Strength Cond Res* 2001;15:109–115. PMID 11708692.
- [S11] TrainingPeaks, "Running Training Stress Score (rTSS) Explained". https://www.trainingpeaks.com/learn/articles/running-training-stress-score-rtss-explained/
- [S12] Suunto, "Training with TSS and hrTSS". https://www.suunto.com/en-gb/sports/News-Articles-container-page/training-with-tss-and-hrtss/
- [S13] Friel J., "Joe Friel's Quick Guide to Setting Zones", TrainingPeaks. https://www.trainingpeaks.com/learn/articles/joe-friel-s-quick-guide-to-setting-zones/
- [S14] Hellard P, et al. Assessing the limitations of the Banister model in monitoring training. *J Sports Sci* 2006;24:509–520. PMID 16608765.
- [S15] Coggan A., "The Science of the TrainingPeaks Performance Manager", TrainingPeaks, 2022/2023. https://www.trainingpeaks.com/learn/articles/the-science-of-the-performance-manager/
- [S16] TrainingPeaks, "What is the Performance Management Chart?". https://www.trainingpeaks.com/learn/articles/what-is-the-performance-management-chart/
- [S17] Hulin BT, Gabbett TJ, Lawson DW, Caputi P, Sampson JA. The acute:chronic workload ratio predicts injury... *Br J Sports Med* 2016. PMID 26511006.
- [S18] Williams S, West S, Cross MJ, Stokes KA. Better way to determine the acute:chronic workload ratio? *Br J Sports Med* 2017;51:209–210. PMID 27650255.
- [S19] Garmin Forerunner 970 Owner's Manual, "Acute Load" / "Load Ratio" / "Training Load Focus". https://www8.garmin.com/manuals-apac/webhelp/forerunner970/EN-SG/GUID-5EC24965-C82C-4FEA-8647-313C08B6F7C7-6714.html
- [S20] Coyle EF, González-Alonso J. Cardiovascular drift during prolonged exercise: new perspectives. *Exerc Sport Sci Rev* 2001;29:88–92. PMID 11337829；Coyle EF. *Int J Sports Med* 1998;19 Suppl 2:S121–4. PMID 9694416.
- [S21] Saunders PU, Pyne DB, Telford RD, Hawley JA. Factors affecting running economy in trained distance runners. *Sports Med* 2004;34:465–485. PMID 15233599.
- [S22] Impellizzeri FM, et al. Acute:Chronic Workload Ratio: Conceptual Issues and Fundamental Pitfalls. *Int J Sports Physiol Perform* 2020;15:907–913. PMID 32502973.
- [S23] Coyne JOC, et al. Does Mathematical Coupling Matter to the Acute to Chronic Workload Ratio? *Int J Sports Physiol Perform* 2019;14:1447–1454. PMID 31672929.
- [S24] Riegel PS. Athletic Records and Human Endurance. *American Scientist* 1981;69(3):285–290.（题录已核实，原文未读）
- [S25] Vickers AJ, Vertosick EA. An empirical study of race times in recreational endurance runners. *BMC Sports Sci Med Rehabil* 2016;8:26. PMID 27570626 / PMC5000509.
- [S26] Daniels J, Gilbert J. *Oxygen Power: Performance Tables for Distance Runners*. 1979；Daniels J. *Daniels' Running Formula*.（书籍，未读，公式按复现版本记录）
- [S27] Garmin Forerunner 970 Owner's Manual, "About VO2 Max. Estimates". https://www8.garmin.com/manuals-apac/webhelp/forerunner970/EN-SG/GUID-63837CA9-4746-4E0E-8B3F-522E4E390C06-1166.html
- [S28] Firstbeat Technologies, "Indirect EPOC Prediction Method Based on Heart Rate Measurement", white paper. https://www.firstbeat.com/wp-content/uploads/2015/10/white_paper_epoc.pdf
- [S29] Firstbeat Technologies, "EPOC Based Training Effect Assessment", white paper. https://www.firstbeat.com/wp-content/uploads/2015/10/white_paper_training_effect.pdf
- [S30] Garmin Forerunner 245 Owner's Manual, "Performance Measurements". https://www8.garmin.com/manuals-apac/webhelp/forerunner245245music/EN-SG/GUID-970180F2-3BDF-432D-947F-05531D5C557F-6581.html
- [S31] Garmin Rumors wiki, "Training Load". https://wiki.garminrumors.com/Training_Load_Focus（社区来源）
- [S32] Garmin Forerunner 970 Owner's Manual, "Viewing Your Predicted Race Times". https://www8.garmin.com/manuals-apac/webhelp/forerunner970/EN-SG/GUID-17EDED75-B9CB-43B1-A72C-5F6F9A337AE3-4210.html
- [S33] Garmin Forums, "race predictor based on vo2 max". https://forums.garmin.com/apps-software/mobile-apps-web/f/garmin-connect-web/83719/race-predictor-based-on-vo2-max ；the5krunner, "Garmin Race Predictor – Still Wrong", 2024. https://the5krunner.com/2024/10/23/garmin-race-predictor-still-wrong/
- [S34] Tanaka H, Monahan KD, Seals DR. Age-predicted maximal heart rate revisited. *J Am Coll Cardiol* 2001;37:153–156. PMID 11153730.
