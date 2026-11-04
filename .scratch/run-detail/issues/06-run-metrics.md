# 06: 本次指标：TRIMP、心率区间、有氧能力值、EF、decoupling

**What to build:** 详情页的"本次指标"区块：TRIMP、各心率区间的时长、本次有氧能力值（或不计入的原因）、EF、60 分钟以上的 decoupling，每项带"怎么算的"。

**Blocked by:** 02

**Status:** done

来源：[实施 spec](../spec.md)，User Stories 17–20；Implementation Decisions 里的"心率区间"和复用说明。

- [x] 写代码前核对 Friel 跑步 LTHR 区间的原始出处，有出入时以出处为准并记在结论里
- [x] 新配置 `[zones]`：`lthr_pct = [85, 90, 95, 100]`；LTHR 按活动日期取当时生效的 `[[physiology]]`
- [x] 心率区间只统计有心率、不在暂停中的秒
- [x] TRIMP 复用 `load` 的逐秒算法；有氧能力值复用 `aerobic_runs` 的条件，不计入时给出具体原因
- [x] EF、decoupling 复用 `longruns` 的口径
- [x] 前端：区间用横向条，其余为数字加"怎么算的"
- [x] Seam 3 测试：各区时长；换 `[[physiology]]` 后按日期取 LTHR；TRIMP 与 `/api/load` 里同一活动一致；不计入有氧能力的原因；59 分钟没有 decoupling

## 结论（实施记录）

- **Friel 区间出处**：TrainingPeaks，Joe Friel, "Joe Friel's Quick Guide to Setting Zones"（2012-05-04 发表，2026-07-18 更新），https://www.trainingpeaks.com/learn/articles/joe-friel-s-quick-guide-to-setting-zones/ 。跑步 LTHR 区间：Z1 < 85%，Z2 85–89%，Z3 90–94%，Z4 95–99%，Z5a 100–102%，Z5b 103–106%，Z5c > 106%。与 spec 一致；唯一差别是出处把 Z5 分成 5a–5c，这里按 spec 合为一个 Z5（≥ 100%），写在 `method.description` 里。每区含下限、不含上限（出处用整数百分比，半开区间与之等价）。
- 接口：`GET /api/activities/{id}` 新增 `metrics` 键（`detail.py` 的 `_metrics`，注册在 `SECTIONS` 的 ticket 06 槽位）。字段：
  - `trimp`、`trimp_source`（`records` 或 `summary_hr`）。
  - `zones`：`lthr_bpm, physiology_effective_from, lthr_pct, total_s, zones[]{zone, low_bpm, high_bpm, seconds, share}`；Z1 的 `low_bpm` 和 Z5 的 `high_bpm` 为 null。
  - `aerobic`：`speed_mps, pace_s_per_km, steady_s, mean_hr, reference_hr`。
  - `ef`：`ef, ef_first, ef_second, steady_s, decoupling_pct, decoupling_high`。
  - `unavailable`：为 null 的项（`trimp`、`zones`、`aerobic`、`ef`、`decoupling`）对应的原因；`method{name, description, params}`。
- 新配置 `[zones]`（`config.py` 的 `Zones`）：`lthr_pct` 默认 `[85, 90, 95, 100]`，必须是 4 个递增的数，否则 `load_config` 报错。LTHR 用 `load.physiology_on` 按活动日期取。
- **区间计时（自定）**：每个采样拥有到它为止的那一秒（`classify_records` 的 `dt_s`），暂停后第一个采样和活动第一个采样不计；只算有心率的秒。TRIMP 沿用 `load` 的口径（到下一个采样的间隔，上限 `max_sample_gap_s`，最后一个采样算 1 秒），所以两者的总秒数可以差一两秒。
- **TRIMP**：`load.py` 抽出 `_trimp_of` 和 `activity_trimp(db, config, activity)`，日负荷和单次活动走同一段代码（`_HR_SECONDS_SQL` 加了 `{where}`）。没有逐秒心率时按摘要平均心率估算（`summary_hr`），同 `/api/load`。
- **有氧能力值**：直接调 `aerobic.aerobic_runs`（只取这一次的开始时间），所以和有氧能力页的点完全一致。不计入时的原因按顺序取第一条：`仅跑步类活动`；`不是户外路跑（跑步机和越野不计入）`；`没有逐秒记录`；`没有心率`；`逐秒记录没有 GPS 位置（像跑步机）`；`逐秒记录没有海拔`；`GPS 漂移：速度超过 X m/s 的秒有 N 秒（上限 60 秒）`；`稳态时间 N 分钟，不足 10 分钟`。
- **EF 与 decoupling 的心率带（与 spec 有出入）**：spec 写"`longruns` 的同一套口径（稳态段去掉心率带条件）"，这是 ticket 13 最初的做法；之后提交 2845fc1 把 `longruns` 改回带心率带（145 ± 15）的稳态段。这里直接调 `longruns._per_run_ef`，沿用现在的口径，保证详情页和长距离表的数字一致；若要去掉心率带，应在 `longruns` 一处改。
- EF 的门槛和有氧能力值相同（户外路跑、`gps_usable`、稳态 ≥ 10 分钟），所以不计入有氧能力的活动也不给 EF，原因相同。decoupling 只给 Garmin 时长 ≥ 60 分钟（`longruns.MIN_DURATION_S`）的活动，否则原因是 `不足 60 分钟，只给 EF，不算 decoupling`；超过 5%（`DECOUPLING_LIMIT_PCT`）时 `decoupling_high` 为 true，前端标红。
- 缺生理参数时区间的原因是 `该日期没有生效的生理参数`；没有逐秒心率但有摘要心率时是 `没有逐秒心率`，都没有时是 `没有心率`。
- 前端：`static/run.js` 的 `metricsSection`（`RENDERERS` 的 ticket 06 槽位）：TRIMP、有氧能力（GAP 配速）、EF、decoupling 为数字，缺项显示原因；心率区间为横向条（区号、bpm 范围、时长、占比）。CSS 在 `style.css` 末尾的 ticket 06 区块。
- 测试 `analysis/tests/test_detail_metrics_api.py`（Seam 3，22 个）：各区时长与边界；按日期换 LTHR；`[zones]` 改下限；暂停和无心率的秒不计；TRIMP 与 `/api/load` 一致、1 小时 HRmax 的已知值、摘要心率估算；没有心率；有氧能力值与 `/api/aerobic` 一致；8 种不计入原因；60 分钟 EF = 1.2、decoupling 0；漂移跑的 EF、decoupling 与 `/api/long-runs` 一致且标红；59 分钟有 EF 没有 decoupling；骑车和跑步机没有 EF。
- 2026-11-04 用户决定：EF 和 decoupling 不限心率带，`longruns` 一起改。详情页 EF 不再以有氧能力值为门槛，改为户外路跑、有逐秒心率、GPS 可用，加上不限心率的稳态时间 ≥ 10 分钟。
