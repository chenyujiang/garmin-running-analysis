# Garmin Connect 数据获取途径调研

Type: research
Status: open
Blocked by: none

## Question

截至 2026 年，从 Garmin Connect 国际版（未开 MFA）以个人身份拉取自己数据，最可行的途径是什么？

具体要查清：

- `garminconnect` / `garth` 等非官方库现在还在维护、还能用吗？登录流程、token 持久化位置和有效期。
- 能拿到哪些数据：活动列表、原始 FIT 文件下载（逐秒数据流）、HRV、静息心率、睡眠，以及 Garmin 自带的 Training Load、VO2max、Race Predictor。
- 限流和锁号的已知行为：回填 5 年历史需要多慢才安全。
- 后备途径：账号数据导出（Garmin 的数据导出请求）里包含什么、什么格式，能否覆盖上面的数据。
