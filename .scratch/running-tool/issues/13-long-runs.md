# 13: 长距离表：EF 和 decoupling

**What to build:** 仪表盘下方有一张长距离表，列出 60 分钟以上的跑步，显示 EF 和 decoupling，decoupling 超过 5% 标红，用来判断长距离的耐力，旁边有"怎么算的"。

**Blocked by:** 11（有氧能力的计算与接口）

**Status:** done

来源：[实施 spec](../spec.md)，User Stories 38、57、58；Implementation Decisions 里的"EF 与 decoupling"。

- [x] EF = GAP 速度 ÷ 心率，只用稳态段
- [x] decoupling 只对 ≥60 分钟的跑步计算，超过 5% 标出
- [x] 长距离接口返回最近的长距离跑步，每行含日期、距离、时长、EF、decoupling，以及公式说明
- [x] 前端表格按原型变体 A 的表格样式，超过 5% 的 decoupling 用红色
- [x] Seam 3 测试：59 分钟的跑步不出现在表里；decoupling 的数值和 >5% 标志正确

## 结论（实施记录）

- 模块 `analysis/src/running/longruns.py`：`long_runs(today=None, limit=10, root=None)`；接口 `GET /api/long-runs?today=YYYY-MM-DD&limit=N`（limit 1–100，默认 10）。
- 返回 `today, has_data, runs[], method{name, description, params}`。`runs[]` 按开始时间新到旧，只含 `today` 及以前：`activity_id, activity_type, start_time_local, distance_m, duration_s, steady_s, ef, ef_first, ef_second, decoupling_pct, decoupling_high`。
- 长距离 = `RUNNING_TYPES` 里 `activities.duration_s >= 3600` 的活动（含跑步机和越野；没有海拔时坡度按 0）。
- 稳态段：复用 `running.aerobic.steady_state`，但去掉"心率在 145 ± 15 内"这一条（`hr_band_bpm = inf`）。理由：decoupling 衡量的正是心率漂移，按参考心率筛掉漂高的秒数会把漂移藏起来。其余条件（热身、在跑、速度稳定、暂停后第一秒、步频锁定）照旧。
- **EF 单位（自定）**：m/min ÷ bpm，按时间加权的平均 GAP 速度 ÷ 平均平滑心率。项目全用公制；Friel 的码/分口径 = 本值 ÷ 0.9144。GAP 用 Minetti 而非 NGP，数值不能与 TrainingPeaks 直接比。写在 `method.description` 和 `method.params.ef_unit`。
- **decoupling 切分（自定）**：稳态秒按累计稳态时间对半分（`method.params.split`），`(EF₁ − EF₂) ÷ EF₁ × 100`。理由：EF 只用稳态段，按原始时间切会让热身和停顿全落在前半。
- 稳态不足 `min_steady_s`（600 s）或没有心率：`ef`、`decoupling_pct` 为 null，`decoupling_high` 为 false。
- 前端 `static/longruns.js`（`longRunsSection()`，`.a-lower` 第 1 列）；`app.js` 新增 `lower()` 行，最近比赛（ticket 15）放第 2 列。CSS 在 `style.css` 末尾 ticket 13 区块（`.a-lower`、`.sec-head`、表格）。
- 测试 `analysis/tests/test_long_runs_api.py`（Seam 3，7 个）：59 分钟不出现、60 分钟出现且 EF = 1.2；formulas.md 算例 5.068% 标红；−5% 和 4% 不标红；排序、limit、today；非跑步类型排除；没有心率时为 null；没有库时 `has_data=false`。测试用 90 s 暂停隔开两半，让平滑窗口不跨两半。
