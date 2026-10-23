# 个人跑步数据分析（Garmin）

Label: wayfinder:map

## Destination

一份可直接开工的技术方案：怎么从 Garmin Connect 国际版拿到全部数据、存在哪、用什么栈、三项核心分析（有氧能力、周跑量与训练负荷、比赛成绩预测）各怎么算。实施不在本地图内。

## Notes

- 领域：个人运动数据分析，单用户，本机运行。
- 账号：Garmin Connect 国际版（garmin.com），未开 MFA。
- 语言：Python。探索阶段用 Jupyter notebook；仪表盘以后再定。
- 数据获取：接受非官方库（`garminconnect` / `garth`）的风险，需限速；手动导出 FIT / 账号数据导出作为后备。
- 凭据：只在本机存 token，密码不落盘。
- 数据范围：跑步活动（要逐秒数据流，不只是汇总）+ HRV、静息心率、睡眠。约 5 年历史，全部要。
- 同步：先一次性回填全部历史，之后增量同步。
- 算法：Garmin 自带指标（Training Load、VO2max、Race Predictor）作参照，主模型自己算（透明、可调）。
- 每次 session 参考：`grilling`、`domain-modeling`；术语见根目录 `GLOSSARY.md`。

## Decisions so far

<!-- the index: one line per closed ticket -->

## Not yet specified

- **数据质量与清洗**：光电心率异常、GPS 漂移、手表暂停/自动暂停、跑步机活动。看过真实数据之后才能说清楚要处理哪些问题。
- **外部因素校正**：温度、坡度、海拔对"同心率下配速"的影响要校正到什么程度。要等有氧能力的指标定义下来。
- **仪表盘**：notebook 稳定后要不要做 Streamlit 之类的本机仪表盘，做的话展示什么。
- **项目骨架与依赖**：Python 版本、包管理（如 `uv`）、DataFrame 库、FIT 解析库。取决于存储方案和数据形态。

## Out of scope

- 写代码实施分析工具：本地图只产出方案。
- 多用户、云部署、手机访问：只给自己本机用。
- Garmin 官方 Connect Developer Program：只对企业开放，个人申请不现实。
