# 13: 长距离表：EF 和 decoupling

**What to build:** 仪表盘下方有一张长距离表，列出 60 分钟以上的跑步，显示 EF 和 decoupling，decoupling 超过 5% 标红，用来判断长距离的耐力，旁边有"怎么算的"。

**Blocked by:** 11（有氧能力的计算与接口）

**Status:** ready-for-agent

来源：[实施 spec](../spec.md)，User Stories 38、57、58；Implementation Decisions 里的"EF 与 decoupling"。

- [ ] EF = GAP 速度 ÷ 心率，只用稳态段
- [ ] decoupling 只对 ≥60 分钟的跑步计算，超过 5% 标出
- [ ] 长距离接口返回最近的长距离跑步，每行含日期、距离、时长、EF、decoupling，以及公式说明
- [ ] 前端表格按原型变体 A 的表格样式，超过 5% 的 decoupling 用红色
- [ ] Seam 3 测试：59 分钟的跑步不出现在表里；decoupling 的数值和 >5% 标志正确
