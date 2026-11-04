# 03: 逐秒曲线

**What to build:** 详情页显示心率、配速、GAP 配速、海拔、步频的曲线，共用一根时间轴，标出暂停、走路和稳态段，带十字线读数。

**Blocked by:** 02

**Status:** open

来源：[实施 spec](../spec.md)，User Stories 10–12；Implementation Decisions 里的"逐秒序列"。

- [ ] 服务端降采样到最多 1500 个点：按时间等分成桶，桶内取均值，暂停时段不跨桶
- [ ] 暂停、走路、稳态以 `[start_s, end_s]` 区间列表返回；稳态复用 `aerobic.steady_state`
- [ ] GAP 复用 `aerobic.gap_speed`；没有海拔时坡度按 0，和长距离表一致
- [ ] 前端：几条曲线上下排列、共用时间轴；区间用浅色底标出；十字线读数沿用有氧能力图的写法
- [ ] Seam 3 测试：点数 ≤ 1500；暂停区间不跨桶；区间的起止秒数；没有心率时心率序列为空并说明
