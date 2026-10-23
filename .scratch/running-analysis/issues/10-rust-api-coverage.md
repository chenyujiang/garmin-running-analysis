# Rust 导入 CLI 如何调用 Garmin 接口

Type: research
Status: resolved
Blocked by: none

## Question

导入 CLI 定为用 Rust 写，但 [Garmin Connect 数据获取途径调研](01-garmin-data-access.md) 推荐的两条途径都只有 Python 客户端。Rust 侧怎么接上？

- **Personal API**：有没有现成的 Rust crate？没有的话，能否从官方 OpenAPI 文档生成客户端（如 `progenitor`、`openapi-generator` 的 Rust 输出），生成质量如何？手写 API key 换 access token 的流程有多复杂？
- **`garminconnect` 才有的指标**（Training Status、VO2max、Race Predictor）：在 Rust 里重新实现它的 mobile SSO 登录和 TLS 伪装（`curl_cffi` 对应的 Rust 方案，如 `rquest` / `wreq`）可行吗，维护成本多大？
- 如果 Rust 侧不值得做，备选方案：Rust CLI 调一个小的 Python 脚本只负责这几项指标；或者干脆不要这几项（它们只是参照）。
- FIT 解析：`fitparser` 等 crate 是否还在维护，能否读开发者字段和私有字段。

## Answer

完整报告在分支 `research/rust-api-coverage` 的 `research/rust-api-coverage.md`（commit `1c5df3f`）。结论：

- **Personal API**：没有现成的 Rust crate。官方 OpenAPI 是 3.0.1，26 个只读 GET，只能从 Swagger 页面的 JS chunk 里提取，并且所有 operation 都缺 `operationId`，`progenitor` 原样读入会报错。推荐用 `reqwest` + `serde` 手写客户端。key 换 token 只是一个 `POST .../personal-api-key/token`，请求头 `Authorization: ApiKey <key>`，响应是纯文本 JWT，过期时间取 payload 里的 `exp`，加缓存约 50 行。如果想省写结构体的工夫，可以给 spec 补上 `operationId` 后用 `progenitor` 或 `typify` 只生成 model。
- **Training Status / VO2max / Race Predictor**：不在 Rust 里重写登录。登录要过 TLS 伪装的 mobile SSO 和 DI OAuth2 换 token；Rust 侧的 `wreq` 能做，但调试一次被拦截就消耗一次登录机会，有锁号风险。现有的 Rust crate（`garmin-cli`、`pulse`）走的都是 2026-03 起被 429 的 OAuth1 旧流程。做法：Rust CLI 通过 `uv run --script` 调一个 PEP 723 Python 小脚本，stdout 只输出 JSON，用退出码区分 429 和认证失败。也可以先不拉这三项。
- **FIT 解析**：用 `fitparser` 0.11.0，默认会保留开发者字段和未知消息。已知 issue #58：开发者字段如果出现在它的描述之前，整个文件解析失败。`rustyfit` 0.11.0 作为备选。原始 FIT 字节要先原样保存，再解析。
- **未验证**：progenitor 对 zip 响应、200/204 混用的处理；DI refresh token 的有效期；两个 FIT crate 在 Windows 上能否构建。

## Comments

- 2026-10-23：「试拉一小批真实数据」实测，Personal API 下载的 FIT 保留了大量 Garmin 私有消息（`unknown_233`、`unknown_325`、`unknown_140` 等，用 Python `fitdecode` 读取）。报告最后一条风险因此基本排除；与 `ORIGINAL` 格式逐字节对比的结果，记录在试拉 ticket 上。
