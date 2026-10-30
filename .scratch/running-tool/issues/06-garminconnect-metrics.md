# 06: garminconnect 小脚本：`login` 与三项 Garmin 指标

**What to build:** 用户运行一次 `runsync login`，交互输入 Garmin 密码，只保存 token。之后的 `runsync sync` 会拉取 Garmin 的 Training Status、VO2max、Race Predictor：回填时每周取一天，之后每次同步存当天的快照，用来和自己算的数字对照。

**Blocked by:** 04（Personal API 活动同步）

**Status:** done

来源：[实施 spec](../spec.md)，User Stories 4、5、17；Implementation Decisions 里的"garminconnect 小脚本"。

- [x] 一个 PEP 723 Python 脚本放在 Rust 项目里，依赖 `garminconnect`；CLI 用 `uv run --script` 调用，脚本路径在编译时由 `CARGO_MANIFEST_DIR` 确定
- [x] 脚本的 `login` 子命令用 `getpass` 读密码，只把 token 存进 `secrets/garminconnect/`；密码不落盘
- [x] 脚本的查询子命令只往 stdout 输出 JSON，用退出码区分成功、限流、认证失败、其他错误
- [x] 第二个数据源实现同一个数据源 trait，请求间隔默认 5 s
- [x] 原始 JSON 按指标、按日期存进原始档案；`garmin_metrics` 每天一行
- [x] 先验证这三项指标能否按日期查历史，结论记在本 ticket；查不了就只存每日快照
- [x] 开发时复用已有 token，不反复调用 `login`（mobile 登录策略已经被 429 过）

## 实现记录

- 脚本：`importer/garminconnect/garmin_metrics.py`（`garminconnect==0.3.20`）。
  - `login --token-dir DIR`：`input` 读 email，`getpass` 读密码，`input` 读 MFA；只 `dump` token。
  - `serve --token-dir DIR --interval S`：常驻进程，只用 token 登录（不传账号密码，token 不可用就退出 3）。stdin 每行一个请求 `<metric> <YYYY-MM-DD>`，stdout 每个请求一行原始 JSON。请求间隔至少 S 秒。第一个错误就退出，不重试。退出前把刷新过的 token 写回。
  - 退出码：0 成功，1 其他，3 token 缺失/过期/被拒，4 限流（429）或 CAPTCHA。
- Rust：`src/garminconnect.rs` 的 `GarminConnectScript` 实现 `MetricsSource`；`runsync login` 直接把终端交给脚本。
- 偏离：没有扩展 `ActivitySource`，而是新增一个同级的 `MetricsSource` trait（共用 `SourceError`）。原因：两个数据源的请求完全不同，而且 ticket 05 同时在改 `ActivitySource`。
- 间隔配置：`config.toml` 的 `[sync] garminconnect_interval_s`，默认 5.0。
- 档案：`raw/garminconnect/<training_status|vo2max|race_predictor>/<YYYY-MM-DD>.json`；`rebuild` 会重新读入。
- 表：`garmin_metrics`（migration `0005`），每天一行，每个指标只写自己的列。
- 同步：每次都重取当天三项并覆盖；回填取今天之前的每个周日，从新到旧，一直到第一条活动所在的那周；已有文件的日期不再请求，所以中断后能续上。结果记进 `sync_runs`（source `garminconnect`）。没有 token 时 `sync` 跳过这个数据源并提示 `runsync login`。

## 历史查询结论

- 库层面：三个端点都带日期参数。`get_training_status(date)` → `/metrics-service/metrics/trainingstatus/aggregated/{date}`；`get_max_metrics(date)` → `/metrics-service/metrics/maxmet/daily/{date}/{date}`；`get_race_predictions(date, date, "daily")` → `/metrics-service/metrics/racepredictions/daily/{displayName}?fromCalendarDate&toCalendarDate`。所以按周回填已经实现。
- 真实 API：**unverified — needs user**。开发环境读不了 `secrets/garminconnect/`（权限被拒），所以没有发真实请求。
- 字段名按库的已知返回结构写的，未经真实响应核对：`mostRecentTrainingStatus.latestTrainingStatusData.<deviceId>.{trainingStatusFeedbackPhrase, primaryTrainingDevice, acuteTrainingLoadDTO.{dailyTrainingLoadAcute, dailyTrainingLoadChronic, dailyAcuteChronicWorkloadRatio}}`；`[].generic.{calendarDate, vo2MaxPreciseValue}`；`[].{calendarDate, time5K, time10K, timeHalfMarathon, timeMarathon}`。
- 需要用户做：运行一次 `runsync sync`，看 `raw/garminconnect/` 下历史周日的文件是否有值。如果历史日期返回的是空或者和当天一样，就去掉回填，只留每日快照。如果字段名不同，就改 `garmin_metrics.rs` 的 `store_metric`，再跑 `runsync rebuild`。
