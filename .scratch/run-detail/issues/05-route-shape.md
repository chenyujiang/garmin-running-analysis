# 05: 路线形状（SVG，无底图）

**What to build:** 详情页用 SVG 画出路线形状，标出起点和终点，带比例尺。不加载任何在线底图，接口不返回绝对经纬度。

**Blocked by:** 02

**Status:** done

来源：[实施 spec](../spec.md)，User Stories 15–16；Implementation Decisions 里的"路线形状"；Further Notes 里的"隐私"。

- [x] 只用有 `lat`/`lon` 的秒；等距矩形投影到以路线中心为原点的米制平面，整体缩放到 `[0, 1]`，保留长宽比
- [x] Douglas–Peucker 简化到最多 500 个点
- [x] 返回 `x, y`、起点和终点下标、比例尺（每单位多少米）；不返回经纬度和中心点
- [x] 没有 GPS 时 `route: null` 并说明原因
- [x] 前端 SVG：路线、起终点标记、比例尺；不引入地图库
- [x] Seam 3 测试：用写在测试文件里的虚构坐标；遍历 JSON 里所有数字，断言没有接近原始经纬度的数；`x, y` 在 `[0, 1]`；长宽比保持；点数 ≤ 500；没有 GPS 时为 null

## 结论（实施记录）

- 后端在 `analysis/src/running/detail.py` 的 route 块，`SECTIONS` 里登记两项：`route`（形状）和 `route_unavailable`（为 null 的原因）。
- `route`：`x, y, start_index, finish_index, metres_per_unit, method`。只查有 `lat`/`lon` 的秒（按时间排序），查询结果只在本块里用，不进 `DetailInputs`。
  - 投影：等距矩形，原点是经纬度包围盒的中心，东西方向乘以中心纬度的余弦，地球半径 6371008.8 m。
  - 归一化（自定）：减去最小 x 和最北的 y 后除以长边的米数，长边占满 `[0, 1]`，短边从 0 开始、不居中。**y 向南增大**（屏幕坐标，北在上），前端直接用。
  - `metres_per_unit` = 简化后保留点的长边米数。
  - 简化（自定细节）：Douglas–Peucker 用优先队列实现，从两端开始，每次拆开"最远点离弦最远"的一段，直到 500 个点，或剩下的点离弦都不到 `tolerance_m = 0.5` m。容差是为了直线段不被浮点噪声填满到 500 个点；0.5 m 远小于 GPS 误差，看不出差别。起点和终点总在，所以 `start_index = 0`、`finish_index = 点数 − 1`。
  - 纯 Python 实现（分析环境没有 numpy）；3000 个拐点的测试路线约 1 秒内完成。
- **为 null 的原因（自定）**：spec 只说 `route: null` 并说明原因，没定字段。用同级的 `route_unavailable`：没有任何 GPS 定位（跑步机、没有逐秒记录）为"没有 GPS 记录（跑步机或室内活动）"；所有定位点在同一处为"GPS 定位点不足，画不出形状"；有路线时为 null。非跑步类活动有 GPS 时照样给路线（spec 的跑步专属清单不含路线）。
- `method.params`：`max_points, tolerance_m, projection`，不含任何坐标。
- 前端 `static/run.js` 的 route 块：`routeSection`，手写 SVG（不用地图库、不加载底图），长边 420 px，路线墨黑折线，空心圆为起点、实心圆为终点，左下比例尺取接近长边 1/4 的整数长度（复用 `svg.js` 的 `niceStep`，文件头多一行 import）。细长路线（如直线往返）给比例尺留最小宽度。没有路线时显示 `route_unavailable`。CSS 在 `style.css` 末尾 ticket 05 区块。
- 测试 `analysis/tests/test_detail_route.py`（Seam 3，6 个），合成数据 `tests/synthetic_route.py` 的 `add_route_run`（新函数，按测试给的轨迹逐秒写 `lat`/`lon`）。坐标是写在测试文件里的虚构点（南太平洋公海）。每个有路线的测试都遍历整个响应 JSON 的所有数字，断言没有任何数在原始纬度或经度 ±0.5° 以内（不计符号）。
  - 2000 × 1000 m 的矩形环线：`x, y` 在 `[0, 1]`，x 占满、y 跨 0.5（长宽比 2:1），比例尺 2000 m，起终点在西南角，四个角都保留，直线段被简化到 ≤ 10 个点。
  - 3000 m 长、每秒一个 2 m 拐点的锯齿：正好 500 个点，比例尺 3000 m。
  - 前 100 秒和后 50 秒没有定位的直线往返：只用有定位的秒，起终点在南端，折返点保留，比例尺 900 m。
  - 有逐秒记录但没有定位的跑步机、没有逐秒记录的活动：`route: null` 加原因；只有一个定位点：`route: null` 加"定位点不足"。
- 前端没有自动测试；用真实数据目测由 ticket 08 做。
