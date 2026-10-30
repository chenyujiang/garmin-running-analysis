# 09: 训练负荷：TRIMP 和 CTL/ATL/TSB，接到仪表盘负荷栏

**What to build:** 用户打开仪表盘，首屏第一栏就能看到这周负荷是否正常：负荷头条（ATL/CTL > 1.5 时标题变红，写成"负荷突增：ATL 是 CTL 的 1.6 倍"，下面一句建议），CTL/ATL/TSB 三个大数字，近 12 周的 CTL/ATL 曲线加 TSB 柱，旁边有"负荷怎么算的"。

**Blocked by:** 03（FIT 解析进 `records` 和 `laps`）

**Status:** done

来源：[实施 spec](../spec.md)，User Stories 7、39–41、49、50、58；Implementation Decisions 里的"训练负荷"。

- [x] 生理参数（HRmax、HRrest、LTHR）按 `config.toml` 里的生效日期取值，每个活动用当时生效的一组
- [x] 逐秒计算 Banister TRIMP，男性系数 `0.64·e^(1.92x)`，`x = (HR − HRrest) / (HRmax − HRrest)`；所有带心率的活动都计入，没有心率的记为缺失，不估算
- [x] CTL 为 42 天 EWMA，ATL 为 7 天，TSB = CTL − ATL；ATL/CTL > 1.5 标为"负荷突增"
- [x] 负荷接口返回当前值、近 12 周序列、突增标志，以及"怎么算的"所需的公式名和当前参数
- [x] 前端用手写 SVG 画负荷栏，视觉按原型变体 A，每张图最多 2 条编辑式批注
- [x] 公式级测试：TRIMP 的数值与原始出处核对（写代码前先核对 Banister 系数出处）
- [x] Seam 3 测试：合成数据下 CTL/ATL/TSB 的数值、突增标志、没有心率的活动记为缺失

## 结论

- **代码位置**：计算在 `analysis/src/running/load.py`（`training_load(today, root)`），接口是 `GET /api/load?today=YYYY-MM-DD`（不传时取今天；页面 URL 上的 `?today=` 会透传）。前端在 `static/load.js`，手写 SVG 的通用部分在 `static/svg.js`。
- **递推选 1/N 形式**：`CTL_t = CTL_{t−1} + (TRIMP_t − CTL_{t−1})/42`，ATL 同理，N=7。
  - 理由：TrainingPeaks 帮助页的转述、WKO 和原型用的都是这一形式，与用户在 TrainingPeaks 里看到的数一致。
  - GoldenCheetah 的 `exp(−1/N)` 形式在 42 天后只差 0.7%，对相对比较没有影响。
  - 递推从第一个活动日开始，初值为 0。选择写进接口的 `method.recursion` 和 `recursion_formula`，"负荷怎么算的"直接显示。
- **TSB = 昨天的 CTL − 昨天的 ATL**，即 TrainingPeaks 的 Form，表示今天出门前的状态。
- **ATL/CTL > 1.5 判为突增**（要求 CTL > 0）。`spike_since` 是截至当前这段连续突增的起始日，用于标题下的建议和图上的批注。
- **逐秒 TRIMP**：Δt 是到下一条 record 的间隔，上限 10 秒（暂停不算），最后一条按 1 秒算。x 截断到 [0, 1]，原文没有规定这一点。只用男性系数 0.64/1.92。
- **缺失**：没有心率记录的活动（包括只有详情 JSON、没有 FIT 的活动）不用平均心率回退，记为缺失，原因是"没有心率"。活动当天没有生效的生理参数也记为缺失，原因是"该日期没有生效的生理参数"。两种都不计入负荷，在 `missing_hr_count` 和 `missing_hr_recent` 里返回。
- **所有活动类型都计入**，按 `start_time_local` 的日期汇总到每天。
- **接口字段**：`as_of`、`has_data`、`current{date,ctl,atl,tsb,ratio}`、`spike`、`spike_since`、`series[{date,trimp,ctl,atl,tsb}]`（最近 84 天）、`missing_hr_count`、`missing_hr_recent`、`config_error`、`method{...}`。`today` 之后的活动不计入，`as_of` 字段回显实际使用的日期。
- **测试向量**取自共享笔记 `formulas.md` 第 1 节（sport-activities-features PR #231 的修正值：32.05 和 261.92）。CTL/ATL 的期望值是按 1/N 递推独立手算的闭式结果。
- **未核实**：Banister 系数没读到原文（Morton 1990、Banister 1991 都返回 403 或只有书），只有同行评审的二手引用，各处一致。
- **附带发现，不属于本 ticket**：stdout 不是 UTF-8 时，`running-dashboard` 的 `main()` 在 `print` 时报 `UnicodeEncodeError: 'charmap' codec can't encode characters`。设 `PYTHONIOENCODING=utf-8` 可以绕过。
