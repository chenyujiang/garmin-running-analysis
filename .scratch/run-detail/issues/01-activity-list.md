# 01: 活动列表：接口、页面和路由

**What to build:** 仪表盘新增"全部活动"页面 `#/runs`，按开始时间倒序列出活动，可以按类型和最小距离筛选、分页。这是本阶段的 tracer bullet：打通 hash 路由、新模块、新接口和 Seam 3 测试。

**Blocked by:** 无

**Status:** open

来源：[实施 spec](../spec.md)，User Stories 1–5；Implementation Decisions 里的 `running/activities.py` 和"仪表盘"。

- [ ] `running/activities.py`：`activity_list(type_filter, min_distance_m, page, page_size, root)`，`type_filter` 为 `running`（`RUNNING_TYPES`）或 `all`
- [ ] 每行含 `activity_id, activity_type, activity_name, start_time_local, distance_m, duration_s, running_pace_s_per_km`（跑步类才有）、`avg_hr_bpm`；返回总数
- [ ] `GET /api/activities?type=&min_km=&page=&page_size=`，`page_size` 1–200，默认 50
- [ ] `app.js` 加 hash 路由：`#/` 首页、`#/runs` 列表、`#/run/<id>` 先显示占位；页头加"全部活动"链接
- [ ] `static/runs.js`：表格、类型和距离筛选、分页，样式沿用变体 A 的表格
- [ ] 没有分析库时显示现有的空状态
- [ ] Seam 3 测试：排序、类型筛选、最小距离、分页总数、`page_size` 越界返回 422、没有库时 `has_data=false`
