# 05: 路线形状（SVG，无底图）

**What to build:** 详情页用 SVG 画出路线形状，标出起点和终点，带比例尺。不加载任何在线底图，接口不返回绝对经纬度。

**Blocked by:** 02

**Status:** open

来源：[实施 spec](../spec.md)，User Stories 15–16；Implementation Decisions 里的"路线形状"；Further Notes 里的"隐私"。

- [ ] 只用有 `lat`/`lon` 的秒；等距矩形投影到以路线中心为原点的米制平面，整体缩放到 `[0, 1]`，保留长宽比
- [ ] Douglas–Peucker 简化到最多 500 个点
- [ ] 返回 `x, y`、起点和终点下标、比例尺（每单位多少米）；不返回经纬度和中心点
- [ ] 没有 GPS 时 `route: null` 并说明原因
- [ ] 前端 SVG：路线、起终点标记、比例尺；不引入地图库
- [ ] Seam 3 测试：用写在测试文件里的虚构坐标；遍历 JSON 里所有数字，断言没有接近原始经纬度的数；`x, y` 在 `[0, 1]`；长宽比保持；点数 ≤ 500；没有 GPS 时为 null
