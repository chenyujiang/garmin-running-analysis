# 04: Personal API 活动同步

**What to build:** 用户运行 `runsync sync`，就能把 Personal API 上的全部活动（所有类型）下载进原始档案，同时写进分析库。中途中断后再次运行，会从停下的地方继续；之后的运行只拉新活动，外加最近 7 天的活动。

**Blocked by:** 03（FIT 解析进 `records` 和 `laps`）

**Status:** done

来源：[实施 spec](../spec.md)，User Stories 3、9–14、16、18、25、26；Implementation Decisions 里的"数据源 trait""Personal API 客户端""原始档案布局""同步算法"。

- [x] 定义数据源 trait，同步逻辑只依赖它；错误用一个小 enum 分三类：限流、凭据失效、其他
- [x] Personal API 客户端用 `reqwest`（blocking）手写：每次运行用 key 换一次 access token，过期时间取 JWT 的 `exp`，接近过期时再换；token 不写盘；日志里不出现 key 或 token
- [x] 活动列表从最新往前翻页，直到某一页的活动在原始档案里全都已有为止
- [x] 下载详情 JSON 和 FIT（zip，解出里面唯一的 FIT 后丢掉 zip），原样存进原始档案；每下载一个文件就解析写库
- [x] 续传只看原始文件是否已存在，不存进度
- [x] 最近 7 天内的活动重新拉取详情 JSON 并覆盖；FIT 只在缺失时下载
- [x] 请求串行发送，间隔取 `config.toml` 里的值，默认 1.5 s
- [x] 回填时显示 `indicatif` 进度条；日志级别由 `RUST_LOG` 控制
- [x] 同步期间 Jupyter 或仪表盘可以同时只读打开分析库（WAL）
- [x] Seam 2 测试：用内存里的假数据源驱动 `sync`，断言原始文件已存在时跳过、翻页在整页都已存在时停止、最近 7 天的详情被覆盖；不测真实 HTTP

## 结论

- **模块**：`importer/src/source.rs`（`ActivitySource` trait、`ListedActivity`、`SourceError { RateLimited(String), CredentialsRejected, Other(anyhow::Error) }`）；`importer/src/sync.rs`（`sync_activities(&DataDir, &mut dyn ActivitySource, &SyncOptions) -> Result<SyncReport>`）；`importer/src/personal_api.rs`（`ApiKey`、`PersonalApiClient`）。
- **"已存在"的判定**：每个活动先下 FIT、后下详情 JSON，所以 `<id>.json` 存在就表示这个活动已完整。中断在两者之间时，下次只补 JSON。文件都先写 `.part` 再改名，档案里不会出现半个文件。
- **没有 FIT 的活动**（手动录入等）：下载接口 404，或 zip 里没有 `.fit`，就只存 JSON。下载内容若本身就是 FIT（不是 zip），原样保存。
- **翻页**：一页里的活动都已有 JSON 就停；但如果这一页最旧的活动仍在最近 7 天内，就继续翻，保证 7 天窗口完整。页大小 100。
- **出错**：数据源任何错误都立即停下这个数据源，已下载的保留，`sync_runs` 记 `rate_limited` / `auth_failed` / `error`，CLI 退出码 1 并给出提示。401/403 记为凭据失效，401/403 响应体里有 `CAPTCHA_REQUIRED` 记为限流。冷却标记留给 ticket 07。
- **凭据**：key 和 token 的类型 `Debug` 输出 `<redacted>`，请求头标记 sensitive，错误信息只含 HTTP 状态和路径，不含响应体。token 只在内存里；距 `exp` 不到 10 分钟时重换；JWT 里读不到 `exp` 时按 1 小时处理。token 接口的响应同时接受纯文本 JWT 和含 `access_token` 的 JSON。
- **配置**：`config.toml` 新增 `[sync] personal_api_interval_s`，默认 1.5。
- **未验证**：真实 HTTP 没有调用过（按规则不测）。活动列表的 `startTimeGMT` 格式、FIT zip 结构、token 响应格式都按调研和官方 Swagger 写的，第一次真实运行（ticket 08）时要确认。
