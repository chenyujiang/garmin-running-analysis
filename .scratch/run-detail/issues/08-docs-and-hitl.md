# 08: 文档更新和真实数据检查（HITL）

**What to build:** 更新 `PRODUCT.md`、`GLOSSARY.md`、`README.md`；用户在真实数据上打开几次跑步检查详情页和报告，必要时调一次报告阈值。

**Blocked by:** 01–07

**Status:** open

来源：[实施 spec](../spec.md)，Implementation Decisions 里的"文档"；Further Notes。

- [ ] `PRODUCT.md`：单次复盘在详情页，跨活动的深入探索仍在 Jupyter
- [ ] `GLOSSARY.md`：心率区间、训练类型、分析报告、配速分布
- [ ] `README.md`：`[zones]`、`[report]` 配置段和新接口
- [ ] 用户检查（agent 不读真实路线坐标，只报汇总数字）：一次轻松跑、一次间歇、一次长距离、一次跑步机、一次非跑步活动；训练类型和配速分布的结论是否符合用户的感觉
- [ ] 结论不符时，记下调整的阈值和理由
