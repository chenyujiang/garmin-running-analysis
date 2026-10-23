# 04: Personal API 活动同步

**What to build:** 用户运行 `runsync sync`，就能把 Personal API 上的全部活动（所有类型）下载进原始档案，同时写进分析库。中途中断后再次运行，会从停下的地方继续；之后的运行只拉新活动，外加最近 7 天的活动。

**Blocked by:** 03（FIT 解析进 `records` 和 `laps`）

**Status:** ready-for-agent

来源：[实施 spec](../spec.md)，User Stories 3、9–14、16、18、25、26；Implementation Decisions 里的"数据源 trait""Personal API 客户端""原始档案布局""同步算法"。

- [ ] 定义数据源 trait，同步逻辑只依赖它；错误用一个小 enum 分三类：限流、凭据失效、其他
- [ ] Personal API 客户端用 `reqwest`（blocking）手写：每次运行用 key 换一次 access token，过期时间取 JWT 的 `exp`，接近过期时再换；token 不写盘；日志里不出现 key 或 token
- [ ] 活动列表从最新往前翻页，直到某一页的活动在原始档案里全都已有为止
- [ ] 下载详情 JSON 和 FIT（zip，解出里面唯一的 FIT 后丢掉 zip），原样存进原始档案；每下载一个文件就解析写库
- [ ] 续传只看原始文件是否已存在，不存进度
- [ ] 最近 7 天内的活动重新拉取详情 JSON 并覆盖；FIT 只在缺失时下载
- [ ] 请求串行发送，间隔取 `config.toml` 里的值，默认 1.5 s
- [ ] 回填时显示 `indicatif` 进度条；日志级别由 `RUST_LOG` 控制
- [ ] 同步期间 Jupyter 或仪表盘可以同时只读打开分析库（WAL）
- [ ] Seam 2 测试：用内存里的假数据源驱动 `sync`，断言原始文件已存在时跳过、翻页在整页都已存在时停止、最近 7 天的详情被覆盖；不测真实 HTTP
