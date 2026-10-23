# 06: garminconnect 小脚本：`login` 与三项 Garmin 指标

**What to build:** 用户运行一次 `runsync login`，交互输入 Garmin 密码，只保存 token。之后的 `runsync sync` 会拉取 Garmin 的 Training Status、VO2max、Race Predictor：回填时每周取一天，之后每次同步存当天的快照，用来和自己算的数字对照。

**Blocked by:** 04（Personal API 活动同步）

**Status:** ready-for-agent

来源：[实施 spec](../spec.md)，User Stories 4、5、17；Implementation Decisions 里的"garminconnect 小脚本"。

- [ ] 一个 PEP 723 Python 脚本放在 Rust 项目里，依赖 `garminconnect`；CLI 用 `uv run --script` 调用，脚本路径在编译时由 `CARGO_MANIFEST_DIR` 确定
- [ ] 脚本的 `login` 子命令用 `getpass` 读密码，只把 token 存进 `secrets/garminconnect/`；密码不落盘
- [ ] 脚本的查询子命令只往 stdout 输出 JSON，用退出码区分成功、限流、认证失败、其他错误
- [ ] 第二个数据源实现同一个数据源 trait，请求间隔默认 5 s
- [ ] 原始 JSON 按指标、按日期存进原始档案；`garmin_metrics` 每天一行
- [ ] 先验证这三项指标能否按日期查历史，结论记在本 ticket；查不了就只存每日快照
- [ ] 开发时复用已有 token，不反复调用 `login`（mobile 登录策略已经被 429 过）
