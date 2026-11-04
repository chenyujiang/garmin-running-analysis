# 06: 本次指标：TRIMP、心率区间、有氧能力值、EF、decoupling

**What to build:** 详情页的"本次指标"区块：TRIMP、各心率区间的时长、本次有氧能力值（或不计入的原因）、EF、60 分钟以上的 decoupling，每项带"怎么算的"。

**Blocked by:** 02

**Status:** open

来源：[实施 spec](../spec.md)，User Stories 17–20；Implementation Decisions 里的"心率区间"和复用说明。

- [ ] 写代码前核对 Friel 跑步 LTHR 区间的原始出处，有出入时以出处为准并记在结论里
- [ ] 新配置 `[zones]`：`lthr_pct = [85, 90, 95, 100]`；LTHR 按活动日期取当时生效的 `[[physiology]]`
- [ ] 心率区间只统计有心率、不在暂停中的秒
- [ ] TRIMP 复用 `load` 的逐秒算法；有氧能力值复用 `aerobic_runs` 的条件，不计入时给出具体原因
- [ ] EF、decoupling 复用 `longruns` 的口径
- [ ] 前端：区间用横向条，其余为数字加"怎么算的"
- [ ] Seam 3 测试：各区时长；换 `[[physiology]]` 后按日期取 LTHR；TRIMP 与 `/api/load` 里同一活动一致；不计入有氧能力的原因；59 分钟没有 decoupling
