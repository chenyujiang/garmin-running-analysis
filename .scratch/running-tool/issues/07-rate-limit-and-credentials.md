# 07: 限流冷却与凭据失效处理

**What to build:** 某个数据源被限流或凭据失效时，`runsync sync` 能安全地停下这个数据源，并告诉用户原因和解决办法；另一个数据源照常完成。

**Blocked by:** 04（Personal API 活动同步），06（garminconnect 小脚本：`login` 与三项 Garmin 指标）

**Status:** done

来源：[实施 spec](../spec.md)，User Stories 19–24。

- [x] 收到 429 或 `CAPTCHA_REQUIRED` 时立即停止这个数据源，不重试
- [x] 在 `state/` 写冷却标记，内容含时间和原因；24 小时内再运行 `sync` 时跳过这个数据源，并说明原因和恢复时间；超过 24 小时自动恢复
- [x] 两个数据源串行处理，互相独立：一个出错不影响另一个
- [x] garminconnect 的 token 失效时提示运行 `runsync login`；Personal API 的 key 被拒绝时提示重新生成 key（约 2027-10 到期）
- [x] `sync` 从不询问密码
- [x] Seam 2 测试：限流后写出冷却标记；冷却期内跳过；超过 24 小时恢复；一个数据源失败时另一个照常完成；两种凭据失效各自输出对应提示

## 结论

- 新模块 `runsync::cooldown`：标记文件 `state/<source>.cooldown.json`，字段 `source`、`since_utc`、`until_utc`（ISO，带 `Z`）、`reason`（如 `rate limited (HTTP 429)`）。`cooldown::active(data_dir, source, now)` 在到期（`now >= until_utc`）时删除标记并返回 `None`，所以超过 24 小时自动恢复；手动删除标记可以提前恢复。标记无法解析时，这个数据源报错（提示删除标记），不会被当成没有冷却。
- 新模块 `runsync::sync_all`：`sync_all(data_dir, &SyncOptions, personal_api: anyhow::Result<&mut dyn ActivitySource>, garminconnect: Option<&mut dyn MetricsSource>) -> SyncAllReport`。先 Personal API，再 garminconnect，串行且互相独立。每个数据源的结果是 `Outcome::{Done, Skipped, Failed}(message)`，消息以数据源名开头。`report.success()` 只在有 `Failed` 时为 false。
- 先查冷却标记，再用数据源：冷却期内不发任何请求，也不需要 key（没有 key 文件时同样跳过，不报错）。冷却跳过和没有 token 的跳过都不算失败，退出码 0。
- 限流（`SourceError::RateLimited`，含 429 和 `CAPTCHA_REQUIRED`）：写标记，输出原因、已完成的部分、恢复时间（本地时间带偏移）和标记路径。凭据失效和其他错误不写标记。
- `main.rs` 只负责构建两个数据源（构建时不联网，也不启动脚本）并打印 `sync_all` 的结果；`Done`/`Skipped` 到 stdout，`Failed` 到 stderr（`error: ...`），有失败时退出码 1。
- `sync` 不询问密码：Personal API 只读 key 文件；garminconnect 只用 `serve`（stdin 是协议管道，只加载 token），交互式 `getpass` 只在 `runsync login` 里。
- 偏差：`tdd` 要求先和用户确认 seam；这里直接用了 spec 里定的 Seam 2（`sync_all` 对接两个假数据源），另加一个 CLI 测试（冷却标记让 `runsync sync` 跳过 Personal API）。
- 测试：`importer/tests/sync_all.rs`（11 个），`importer/tests/cli.rs` 新增 1 个。
