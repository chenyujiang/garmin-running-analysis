# 07: 分析报告（固定规则）

**What to build:** 详情页最上面一段中文分析报告：训练类型、有氧能力对比、心率漂移、配速分布、负荷、气温。每条带规则名、结论级别、实际数值和阈值；阈值在 `config.toml` 里可调。

**Blocked by:** 03、04、06

**Status:** open

来源：[实施 spec](../spec.md)，User Stories 21–30；Implementation Decisions 里的"分析报告"。

- [ ] `running/report.py`：纯函数 `run_report(detail, context)`，每条含 `rule, verdict, text, params`，`verdict` 为 `good`、`neutral`、`watch`、`unknown`
- [ ] 六条规则按 spec 实现：训练类型、有氧能力对比、心率漂移、配速分布、负荷、气温
- [ ] 新配置 `[report]`，默认值见 spec；气温阈值沿用 `[aerobic].hot_week_c`
- [ ] 判断不了的规则说明原因（没有心率、没有 GPS、太短、非跑步类）
- [ ] 报告并入 `GET /api/activities/{activity_id}` 的返回
- [ ] 前端：每条一行，结论在前，规则和数值可展开；watch 用红色 `#b0281f`
- [ ] Seam 3 测试：每条规则命中和不命中各一个合成活动；改 `[report]` 阈值后结论随之改变
