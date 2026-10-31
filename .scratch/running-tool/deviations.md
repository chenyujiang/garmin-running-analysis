# 与 spec 的偏离

## 已确认保留的偏离

下面五项是实现时做的取舍，code review 时没有改。用户 2026-10-31 确认全部保留，spec 已按此更新。

1. **跑步类型有 9 种**（`RUNNING_TYPES`）：除了 spec 写的几种，还包括 Garmin 的其他跑步子类型（跑道、越野、跑步机、虚拟跑等）。负荷、周跑量和长距离都按这 9 种来算。
2. **TSB 用的是昨天的 CTL/ATL**：TSB = CTL(昨天) − ATL(昨天)，也就是今天训练之前的状态（TrainingPeaks 的口径）。spec 写的是同一天的 CTL − ATL。
3. **Riegel 指数 k 截断在 [1.01, 1.20]**：用两场比赛拟合出来的 k 超出这个范围时会被截断，避免数据离谱时给出离谱的预测。
4. **`MetricsSource` 是一个单独的 trait**：Garmin 三项参照指标的同步，用的是自己的 trait，而不是和活动同步共用一个 source 抽象。
5. **冷却期内退出码为 0**：Garmin 限流后进入 24 小时冷却期，这期间运行 `runsync sync` 会跳过 Garmin 指标，打印提示，退出码仍然是 0，不当作失败。

## 其他已确认的决定

- **训练状态统一写法**（2026-10-31）：API 的 `trainingStatusFeedbackPhrase` 带数字后缀（`PRODUCTIVE_1`），导出包没有（`PRODUCTIVE`）。`garmin_metrics.training_status` 统一存不带后缀的名字（`importer/src/garmin_metrics.rs` 的 `training_status_name`）。
