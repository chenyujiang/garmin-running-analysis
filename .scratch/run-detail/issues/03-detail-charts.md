# 03: 逐秒曲线

**What to build:** 详情页显示心率、配速、GAP 配速、海拔、步频的曲线，共用一根时间轴，标出暂停、走路和稳态段，带十字线读数。

**Blocked by:** 02

**Status:** done

来源：[实施 spec](../spec.md)，User Stories 10–12；Implementation Decisions 里的"逐秒序列"。

- [x] 服务端降采样到最多 1500 个点：按时间等分成桶，桶内取均值，暂停时段不跨桶
- [x] 暂停、走路、稳态以 `[start_s, end_s]` 区间列表返回；稳态复用 `aerobic.steady_state`
- [x] GAP 复用 `aerobic.gap_speed`；没有海拔时坡度按 0，和长距离表一致
- [x] 前端：几条曲线上下排列、共用时间轴；区间用浅色底标出；十字线读数沿用有氧能力图的写法
- [x] Seam 3 测试：点数 ≤ 1500；暂停区间不跨桶；区间的起止秒数；没有心率时心率序列为空并说明

## 结论（实施记录）

- 代码在 `analysis/src/running/detail.py` 的 ticket 03 块：`_series(d)`，在 `SECTIONS` 里注册为 `"series"`。`GET /api/activities/{id}` 多出 `series`：`duration_s`、`bucket_s`、`t_s`、`hr_bpm`、`pace_s_per_km`、`gap_pace_s_per_km`、`altitude_m`、`cadence_spm`、`intervals{pause, walking, steady}`、`unavailable`、`method`。
- 时间轴：从第一个采样起的墙钟秒数，暂停照实占位（不压缩），这样和 Garmin 回放的时间对得上。
- 降采样：桶宽取整秒，选最小的 w，使"每段不含暂停的时间各自按 w 分桶"后的桶总数 ≤ 1500（`MAX_POINTS`）。暂停（采样间隔 > `run_walk.pause_gap_s`，默认 10 秒）把记录切成段，桶从每段的第一个采样起算，所以桶永远不跨暂停。桶内对 t、心率、速度、GAP 速度、海拔、步频取算术平均，结果保留 1 位小数。
- 配速 = 1000 / 桶内平均速度；平均速度低于 0.5 m/s（`MIN_PACE_SPEED_MPS`）的桶配速为 null，前端在那里断线，不画到几十分钟每公里。
- GAP：直接用 `aerobic.steady_state` 输出的 `gap_mps`（内部调 `gap_speed`，用 30 秒平滑速度、30 秒窗口坡度，限幅 ±0.15）。和长距离表同一口径；没有海拔时坡度按 0，GAP 等于配速。
- 区间：一个采样代表"到它为止的 dt_s 秒"，所以一段连续标记的区间是 [第一个采样的 t − dt_s, 最后一个采样的 t]。暂停区间 = [暂停前最后一个采样, 恢复后第一个采样]，暂停总是切断走路段和稳态段。
- 走路段 = 跑走分类判为走的秒（10 秒尾随平均步频 < 140 spm），因此边界比真实切换晚约 5 秒。稳态段用完整的 `steady_state` 过滤，含热身 10 分钟和心率带 145 ± 15 bpm，和有氧能力图、长距离表的稳态一致。
- 缺数据：没有逐秒记录时所有序列和区间都是 `[]`，原因"没有逐秒记录"；没有心率时 `hr_bpm` 和 `steady` 为 `[]`，原因"没有心率记录"；同理"没有速度记录""没有海拔记录""没有步频记录"。非跑步类活动只给心率和海拔，配速、GAP、步频、走路段、稳态段为 `null`，原因"仅跑步类活动"。
- `steady_state` 在 `_series` 函数内局部导入，避免和并行的 ticket 04–06 抢改文件顶部的 import 块。
- 前端在 `static/run.js` 的 ticket 03 块：`seriesSection`。心率、配速（y 轴反向，快在上，GAP 配速虚线叠在同一张图）、海拔、步频四张图上下排列，只在最下面一张标时间刻度。y 轴取 2%–98% 分位数再留 8% 边，尖刺夹到边上。暂停、走路、稳态用浅色底标出，图例只列这次有的区间。十字线照有氧能力图的写法：一根虚线穿过所有图、吸附到最近的桶，读数一行列出时刻、所在区间和各项数值。缺的序列不画，在图下用一行小字说明原因。没有改 `style.css`，色块用 SVG 内联填色。
- 测试：`analysis/tests/test_detail_series_api.py` 共 7 个 Seam 3 测试（两小时跑步降到 1000–1500 个点；11 秒暂停两侧不同心率、15 秒桶不混；走路和稳态区间的起止秒数；无心率；骑行；10% 上坡的 GAP 值和无海拔；无逐秒记录）。合成数据新加 `synthetic_aerobic.add_paused_hr_run`，带暂停的心率跑步。
