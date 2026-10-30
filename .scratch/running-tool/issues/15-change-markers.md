# 15: "上次打开以来变化"红点

**What to build:** 用户打开仪表盘时，上次打开以来发生变化的数字旁边有红点；点一下"全部标为已读"就清掉全部红点。

**Blocked by:** 09（训练负荷：TRIMP 和 CTL/ATL/TSB，接到仪表盘负荷栏），10（跑和走的分类与周跑量，接到仪表盘跑量栏），14（成绩预测与比赛）

**Status:** done

来源：[实施 spec](../spec.md)，User Story 59。

- [x] 用浏览器 localStorage 记录上次看到的值，服务端不写任何东西
- [x] 负荷、跑量、预测里的头条数字变化时显示红点
- [x] "全部标为已读"把当前值存为已读，红点全部消失
- [x] 第一次打开（localStorage 为空）时不显示红点
- [x] 在浏览器里检查：改动合成数据后刷新出现红点，标为已读后消失

## 结论

- 新模块 `analysis/src/running/dashboard/static/changes.js`：纯逻辑 `createTracker(storage)`（`observe(key, shown)`、`changedKeys()`、`markAllRead()`、`subscribe(fn)`），浏览器胶水 `watch(el, key, shown)`（变了就在 `el` 末尾加 `span.new-dot`，title 写上次已读的值）和 `markAllReadButton()`（顶栏同步时间左边，"N 处有变化 · 全部标为已读"，没有变化时隐藏）。
- localStorage 键 `running-dashboard.seen.v1`，值是 `{key: 显示文本}`。比较的是页面上显示的文本，不是原始浮点数，所以四舍五入抖动不算变化。
- 跟踪的数字：负荷 `load.ctl/atl/tsb`；跑量 `volume.this_week/last_week/rolling_7d`（km 一位小数）；预测 `predict.5k/10k/half/marathon`（预测列）。
- 决定：第一次打开（或新出现的数字）没有已读值时不显示红点，并把当前值直接记为已读基线，否则第一次打开后永远没有对照。之后已读值只在点"全部标为已读"时更新，所以红点在刷新后保留，直到点按钮。
- localStorage 不可用或内容损坏时不显示红点，不报错。
- 测试：`analysis/tests/js/changes.test.mjs`（`node --test`，8 个用例），由 `tests/test_changes_js.py` 在 `uv run pytest` 里跑；没装 Node 时跳过。
- 浏览器检查（临时合成数据目录，端口 8795）：首次打开 0 个红点；改合成数据后刷新出现 10 个红点和"10 处有变化"按钮；点击后红点全部消失、按钮隐藏，再刷新仍为 0。
