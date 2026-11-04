# 04: 分段：圈和每公里

**What to build:** 详情页两张表：手表的圈分段，和按距离切的每公里分段。

**Blocked by:** 02

**Status:** open

来源：[实施 spec](../spec.md)，User Stories 13–14；Implementation Decisions 里的"每公里分段""圈分段"。

- [ ] 圈：取 `laps` 表，`avg_cadence` ×2 换成 spm
- [ ] 每公里：按 `records.distance` 每满 1000 m 一段，最后不足 1 km 的一段单独列出并标明距离
- [ ] 每公里每段：跑步配速（只算跑的秒）、GAP 配速、平均心率、平均 spm、海拔升降
- [ ] 非跑步类活动没有每公里分段（null 加原因）；没有圈时圈表为空并说明
- [ ] Seam 3 测试：段数、最后一段距离、spm 换算、某段含走路时跑步配速不含走路
