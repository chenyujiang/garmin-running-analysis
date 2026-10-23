# 07: 限流冷却与凭据失效处理

**What to build:** 某个数据源被限流或凭据失效时，`runsync sync` 能安全地停下这个数据源，并告诉用户原因和解决办法；另一个数据源照常完成。

**Blocked by:** 04（Personal API 活动同步），06（garminconnect 小脚本：`login` 与三项 Garmin 指标）

**Status:** ready-for-agent

来源：[实施 spec](../spec.md)，User Stories 19–24。

- [ ] 收到 429 或 `CAPTCHA_REQUIRED` 时立即停止这个数据源，不重试
- [ ] 在 `state/` 写冷却标记，内容含时间和原因；24 小时内再运行 `sync` 时跳过这个数据源，并说明原因和恢复时间；超过 24 小时自动恢复
- [ ] 两个数据源串行处理，互相独立：一个出错不影响另一个
- [ ] garminconnect 的 token 失效时提示运行 `runsync login`；Personal API 的 key 被拒绝时提示重新生成 key（约 2027-10 到期）
- [ ] `sync` 从不询问密码
- [ ] Seam 2 测试：限流后写出冷却标记；冷却期内跳过；超过 24 小时恢复；一个数据源失败时另一个照常完成；两种凭据失效各自输出对应提示
