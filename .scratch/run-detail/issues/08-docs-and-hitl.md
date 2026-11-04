# 08: 文档更新和真实数据检查（HITL）

**What to build:** 更新 `PRODUCT.md`、`GLOSSARY.md`、`README.md`；用户在真实数据上打开几次跑步检查详情页和报告，必要时调一次报告阈值。

**Blocked by:** 01–07

**Status:** open

来源：[实施 spec](../spec.md)，Implementation Decisions 里的"文档"；Further Notes。

- [x] `PRODUCT.md`：单次复盘在详情页，跨活动的深入探索仍在 Jupyter
- [x] `GLOSSARY.md`：心率区间、训练类型、分析报告、配速分布
- [x] `README.md`：`[zones]`、`[report]` 配置段和新接口
- [ ] 用户检查（agent 不读真实路线坐标，只报汇总数字）：一次轻松跑、一次间歇、一次长距离、一次跑步机、一次非跑步活动；训练类型和配速分布的结论是否符合用户的感觉
- [x] 结论不符时，记下调整的阈值和理由

## 阈值调整

- 2026-11-04 `interval_speed_ratio` 0.15 → 0.10。用户在真实数据上看到一次间歇跑被判成混合。推测是快段比全程中位速度快不到 15%，凑不够 `interval_min_reps` 段：中位速度本身已含快段，15% 对快慢差不大的间歇过严（未逐秒核对这次跑）。`interval_min_s`、`interval_min_reps` 不变。
