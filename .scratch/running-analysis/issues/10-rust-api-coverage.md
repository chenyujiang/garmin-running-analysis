# Rust 导入 CLI 如何调用 Garmin 接口

Type: research
Status: open
Blocked by: none

## Question

导入 CLI 定为用 Rust 写，但 [Garmin Connect 数据获取途径调研](01-garmin-data-access.md) 推荐的两条途径都只有 Python 客户端。Rust 侧怎么接上？

- **Personal API**：有没有现成的 Rust crate？没有的话，能否从官方 OpenAPI 文档生成客户端（如 `progenitor`、`openapi-generator` 的 Rust 输出），生成质量如何？手写 API key 换 access token 的流程有多复杂？
- **`garminconnect` 才有的指标**（Training Status、VO2max、Race Predictor）：在 Rust 里重新实现它的 mobile SSO 登录和 TLS 伪装（`curl_cffi` 对应的 Rust 方案，如 `rquest` / `wreq`）可行吗，维护成本多大？
- 如果 Rust 侧不值得做，备选方案：Rust CLI 调一个小的 Python 脚本只负责这几项指标；或者干脆不要这几项（它们只是参照）。
- FIT 解析：`fitparser` 等 crate 是否还在维护，能否读开发者字段和私有字段。
