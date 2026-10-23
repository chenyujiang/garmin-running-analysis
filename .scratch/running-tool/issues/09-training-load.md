# 09: 训练负荷：TRIMP 和 CTL/ATL/TSB，接到仪表盘负荷栏

**What to build:** 用户打开仪表盘，首屏第一栏就能看到这周负荷是否正常：负荷头条（ATL/CTL > 1.5 时标题变红，写成"负荷突增：ATL 是 CTL 的 1.6 倍"，下面一句建议），CTL/ATL/TSB 三个大数字，近 12 周的 CTL/ATL 曲线加 TSB 柱，旁边有"负荷怎么算的"。

**Blocked by:** 03（FIT 解析进 `records` 和 `laps`）

**Status:** ready-for-agent

来源：[实施 spec](../spec.md)，User Stories 7、39–41、49、50、58；Implementation Decisions 里的"训练负荷"。

- [ ] 生理参数（HRmax、HRrest、LTHR）按 `config.toml` 里的生效日期取值，每个活动用当时生效的一组
- [ ] 逐秒计算 Banister TRIMP，男性系数 `0.64·e^(1.92x)`，`x = (HR − HRrest) / (HRmax − HRrest)`；所有带心率的活动都计入，没有心率的记为缺失，不估算
- [ ] CTL 为 42 天 EWMA，ATL 为 7 天，TSB = CTL − ATL；ATL/CTL > 1.5 标为"负荷突增"
- [ ] 负荷接口返回当前值、近 12 周序列、突增标志，以及"怎么算的"所需的公式名和当前参数
- [ ] 前端用手写 SVG 画负荷栏，视觉按原型变体 A，每张图最多 2 条编辑式批注
- [ ] 公式级测试：TRIMP 的数值与原始出处核对（写代码前先核对 Banister 系数出处）
- [ ] Seam 3 测试：合成数据下 CTL/ATL/TSB 的数值、突增标志、没有心率的活动记为缺失
