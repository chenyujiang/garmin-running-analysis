# 02: 详情页骨架：概要和入口链接

**What to build:** `#/run/<id>` 显示单次活动的概要；活动列表、首页长距离表和最近比赛表的行都链接到这里。不存在的 id 给出明确提示。

**Blocked by:** 01

**Status:** open

来源：[实施 spec](../spec.md)，User Stories 6–9；Implementation Decisions 里的 `running/detail.py` 和"非跑步类活动"。

- [ ] `running/detail.py`：`activity_detail(activity_id, root)`，先只含概要
- [ ] 概要：距离、时长、跑步配速（复用 `runwalk`）、Garmin 平均配速作参照、平均和最大心率、平均 spm、累计爬升、气温（复用 `aerobic.air_temperature`）
- [ ] `GET /api/activities/{activity_id}`；不存在时 404，JSON 带中文说明
- [ ] 非跑步类活动：跑步专属字段为 null，带原因"仅跑步类活动"
- [ ] `static/run.js`：概要区块；列表行、长距离表、最近比赛表（有 `activity_id` 时）加链接
- [ ] Seam 3 测试：概要数值；404；非跑步类活动的 null 和原因
