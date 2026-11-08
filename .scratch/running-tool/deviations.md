# 与 spec 的偏离

## 已确认保留的偏离

下面五项是实现时做的取舍，code review 时没有改。用户 2026-10-31 确认全部保留，spec 已按此更新。

1. **跑步类型有 9 种**（`RUNNING_TYPES`）：除了 spec 写的几种，还包括 Garmin 的其他跑步子类型（跑道、越野、跑步机、虚拟跑等）。负荷、周跑量和长距离都按这 9 种来算。
2. **TSB 用的是昨天的 CTL/ATL**：TSB = CTL(昨天) − ATL(昨天)，也就是今天训练之前的状态（TrainingPeaks 的口径）。spec 写的是同一天的 CTL − ATL。
3. **Riegel 指数 k 截断在 [1.01, 1.20]**：用两场比赛拟合出来的 k 超出这个范围时会被截断，避免数据离谱时给出离谱的预测。
4. **`MetricsSource` 是一个单独的 trait**：Garmin 三项参照指标的同步，用的是自己的 trait，而不是和活动同步共用一个 source 抽象。
5. **冷却期内退出码为 0**：Garmin 限流后进入 24 小时冷却期，这期间运行 `runsync sync` 会跳过 Garmin 指标，打印提示，退出码仍然是 0，不当作失败。

## 待确认的偏离

推送 5K 计划到 Garmin Connect（PR #10，`running-push-plan`）偏离了 spec 的两条约束，code review 时提出，等用户确认。spec 已按此先改。

1. **Python 调用导入端的 garminconnect 脚本**：spec 原本写两边只通过数据目录交换数据。推送需要 garminconnect 的 token 和客户端，这些只在 `importer/garminconnect/garmin_metrics.py` 里，所以 `running-push-plan --apply` 用 `uv run --script` 启动它的 `push` 子命令，经 stdin/stdout 交换 JSON。分析库仍然只读。
2. **Python 写 `state/`**：spec 原本写分析包只读、`state/` 只放冷却标记。推送把 Garmin 返回的 id 写进 `state/plan5k_push.json`（防重复、`--replace` 只删自己建的），限流时写和 `runsync sync` 相同格式的 `state/garminconnect.cooldown.json`，冷却期内拒绝推送。
3. **新的测试接缝**：`push_plan.main` 接受 `runner` 参数，测试用它把导入端脚本的 `push()` 接到假 Garmin 客户端上；另有一个测试用存根 `garminconnect` 包真实运行脚本的 `push` 子命令，检查中文名称在任何控制台代码页下都不乱码。

## 其他已确认的决定

- **训练状态统一写法**（2026-10-31）：API 的 `trainingStatusFeedbackPhrase` 带数字后缀（`PRODUCTIVE_1`），导出包没有（`PRODUCTIVE`）。`garmin_metrics.training_status` 统一存不带后缀的名字（`importer/src/garmin_metrics.rs` 的 `training_status_name`）。
