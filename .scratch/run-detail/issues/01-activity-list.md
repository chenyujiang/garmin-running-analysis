# 01: 活动列表：接口、页面和路由

**What to build:** 仪表盘新增"全部活动"页面 `#/runs`，按开始时间倒序列出活动，可以按类型和最小距离筛选、分页。这是本阶段的 tracer bullet：打通 hash 路由、新模块、新接口和 Seam 3 测试。

**Blocked by:** 无

**Status:** done

来源：[实施 spec](../spec.md)，User Stories 1–5；Implementation Decisions 里的 `running/activities.py` 和"仪表盘"。

- [x] `running/activities.py`：`activity_list(type_filter, min_distance_m, page, page_size, root)`，`type_filter` 为 `running`（`RUNNING_TYPES`）或 `all`
- [x] 每行含 `activity_id, activity_type, activity_name, start_time_local, distance_m, duration_s, running_pace_s_per_km`（跑步类才有）、`avg_hr_bpm`；返回总数
- [x] `GET /api/activities?type=&min_km=&page=&page_size=`，`page_size` 1–200，默认 50
- [x] `app.js` 加 hash 路由：`#/` 首页、`#/runs` 列表、`#/run/<id>` 先显示占位；页头加"全部活动"链接
- [x] `static/runs.js`：表格、类型和距离筛选、分页，样式沿用变体 A 的表格
- [x] 没有分析库时显示现有的空状态
- [x] Seam 3 测试：排序、类型筛选、最小距离、分页总数、`page_size` 越界返回 422、没有库时 `has_data=false`

## 结论（实施记录）

- 模块 `analysis/src/running/activities.py`：`activity_list(type_filter="running", min_distance_m=None, page=1, page_size=50, root=None)`；接口 `GET /api/activities?type=running|all&min_km=<float>&page=<int>&page_size=<int>`（`type` 只接受这两个值，否则 422；`min_km ≥ 0`；`page ≥ 1`；`page_size` 1–200，默认 50，越界 422）。
- 返回 `has_data, type_filter, min_distance_m, page, page_size, total, activities[], method{name, description, params}`。`activities[]`：`activity_id, activity_type, activity_name, start_time_local, distance_m, duration_s, running_pace_s_per_km, avg_hr_bpm`。`min_distance_m` 是米（接口收 km，乘 1000）。
- 排序：`start_time_local` 降序，同时刻按 `activity_id` 降序，保证分页稳定。
- **`has_data`（自定）**：分析库里有任何活动就是 true，与筛选无关。筛选后没有结果时前端显示"没有符合筛选条件的活动"，不显示空状态；只有没有库（或库里没有活动）时显示首页同款空状态。
- **最小距离（自定）**：按 `activities.distance_m`（Garmin 距离）筛；设了最小距离时，没有距离的活动不列出。
- **跑步配速**：复用 `runwalk.running_summaries`，只算当前页里的跑步类活动。为此给它加了关键字参数 `activity_ids`（不传时行为不变），避免 1500 个活动每次全量分类。没有步频数据时照旧回落到 Garmin 总距离和总时长；非跑步类为 null。
- 前端：`app.js` 加 hash 路由（`parseRoute`）：`#/`（或空、或未知 hash）首页，`#/runs` 列表，`#/run/<id>` 先显示占位；`hashchange` 时重新读状态并渲染。没有库时所有路由都显示现有空状态。页头加导航"首页 / 全部活动"，当前页用 `aria-current` 标出；品牌名链接回首页。
- **筛选和页码放在 hash 查询串里（自定）**：`#/runs?type=all&min_km=10&page=2`，刷新和收藏后保持。
- `static/runs.js`：`runsPage(query)`；类型切换沿用 `.seg` 按钮组，距离用下拉（不限、≥5、10、15、21、30 km）；每页 50 行；日期和名称链接到 `#/run/<id>`。活动类型显示为中文名（常见几种），不认识的显示原始 key。CSS 在 `style.css` 末尾 run-detail ticket 01 区块。
- 合成数据：`tests/synthetic.py` 的 `insert_activity` 加了 `activity_name`、`avg_hr_bpm` 两个可选参数。
- 测试 `analysis/tests/test_activities_api.py`（Seam 3，12 个函数，参数化后 14 个）：排序和行字段；跑步配速不含走路（与周跑量同一个算例，约 333 s/km）、非跑步类为 null、没有记录时用 Garmin 总量；类型默认跑步类、`all` 全部、未知类型 422；最小距离边界（9999 m 不列、10000 m 列）和无距离活动；分页和总数；`page_size` 0、201 和 `page` 0 返回 422，200 可以；没有库时 `has_data=false`；筛选为空时 `has_data` 仍为 true。
