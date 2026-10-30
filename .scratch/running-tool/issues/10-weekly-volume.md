# 10: 跑和走的分类与周跑量，接到仪表盘跑量栏

**What to build:** 每次跑步的配速只按跑的秒计算，跑完后走路的时间不再拖慢数字。仪表盘首屏第二栏显示本周、上周和滚动 7 天的跑量，以及近 12 周柱状图（本周还没跑完，柱子用灰色），旁边有"跑量怎么算的"。

**Blocked by:** 03（FIT 解析进 `records` 和 `laps`）

**Status:** done

来源：[实施 spec](../spec.md)，User Stories 32、33、42、51、58；Implementation Decisions 里的"跑和走"和"周跑量"。

- [x] 步频 ×2 得到 spm，10 秒平滑，≥140 spm 算跑；连续走不到 10 秒的仍算跑；阈值从 `config.toml` 读，代码里有默认值
- [x] 跑步配速 = 跑的秒的距离 ÷ 跑的秒的时长；Garmin 的平均配速作参照保留
- [x] 周跑量只统计跑步类活动（路跑、跑步机、越野都算），只算跑的秒的距离；按 `start_time_local` 的自然周（周一到周日）统计，另给滚动 7 天的值
- [x] 跑量接口返回本周、上周、滚动 7 天、近 12 周序列，以及公式说明和参数
- [x] 前端用手写 SVG 画跑量栏，视觉按原型变体 A
- [x] Seam 3 测试：合成数据下中途有走路的跑步、跨周的活动、跑步机活动，断言周跑量和跑步配速的数值

## 结论

- 跑走分类在 `analysis/src/running/runwalk.py`，周跑量在 `analysis/src/running/volume.py`，接口 `GET /api/volume`（可选 `?today=YYYY-MM-DD` 固定日期）。
- 平滑后被判为走的一段，只有其中原始（未平滑）走的秒数不到 10 秒才改回跑：平滑会把 8 秒的停顿拉长到约 15 秒，直接按平滑后的长度判断会漏掉短停。
- 采样间隔超过 30 秒（`pause_gap_s`）当作手表暂停，这段时间和距离都不计。
- 没有步频的跑步（无 FIT 或 FIT 无 cadence）回退到 Garmin 的总距离和总时长，`source = "activity"`。
- 跨午夜或跨周的活动整次算在开始那天、开始那一周。
- 跑步类活动类型集合扩到 9 种（含 track、indoor、ultra、obstacle、virtual），见 `RUNNING_TYPES`。
- 阈值在 `config.toml` 的 `[run_walk]` 表：`cadence_spm`、`smoothing_s`、`min_walk_s`、`pause_gap_s`。
- 前端 `static/volume.js` 自己取数，占首屏第 2 栏；负荷栏（09）和预测栏加到 `app.js` 的 `band()` 里。
- 测试：`analysis/tests/test_volume_api.py` 15 个，合成数据 helper 在 `analysis/tests/synthetic.py`。
