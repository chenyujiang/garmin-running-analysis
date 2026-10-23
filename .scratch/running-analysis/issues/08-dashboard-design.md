# 分析仪表盘的设计

Type: prototype
Status: resolved
Blocked by: none

## Question

三项核心分析（有氧能力长期趋势、周跑量与训练负荷、比赛成绩预测）在一个本机仪表盘里应该怎么呈现？

- 用 `impeccable` 做设计：信息层级、布局、图表类型、配色和字体、空状态（数据还没同步时）。
- 做一个粗糙的可交互原型（静态数据即可），先看效果再定细节。
- 原型要能回答：Streamlit 这类现成框架能不能达到这个设计，还是需要自己写前端。这一点决定技术栈。

具体指标公式还没定（见 [有氧能力指标的定义](06-aerobic-metric.md)、[训练负荷模型与成绩预测方法](07-load-and-prediction.md)），原型里先用示意数据。

## Comments

- 2026-10-23：要展示的指标已经定下来，见 [有氧能力指标的定义](06-aerobic-metric.md) 和 [训练负荷模型与成绩预测方法](07-load-and-prediction.md)：有氧能力周趋势（附每周平均温度）、EF、decoupling；CTL/ATL/TSB 和"负荷突增"提示；周跑量；各距离成绩预测（含"过期"状态和 Garmin 参照值）。
- 2026-10-23（来自 [项目骨架与依赖](11-project-skeleton.md)）：计算逻辑放在 `analysis/src/running/` 包里，仪表盘直接复用。分析侧用 polars 和 DuckDB，不依赖 pandas；分析库在数据目录的 `running.sqlite`，只读打开。

## Answer

2026-10-23 看过原型后确定。原型在丢弃用的分支 `prototype/dashboard`（commit `9cf22b6`），不合并进 main：`.scratch/running-analysis/prototype/dashboard.html` 是静态 HTML 原型，`streamlit/app.py` 是 Streamlit 对照版。两者都用合成数据。查看方法：`git worktree add ../garmin-proto prototype/dashboard`，再在浏览器打开 `dashboard.html?variant=A`。

**视觉方向**：报纸体育版的数据图形。新闻纸色的底、墨黑文字，红色只用于批注和警告；标题用衬线字（Noto Serif SC），正文和数字用 IBM Plex Sans + Noto Sans SC，数字用 tabular-nums。每张图最多 2 条编辑式批注。上次打开之后变化的数字旁边加红点，可以一键"全部标为已读"。产品背景和优先级写在根目录 `PRODUCT.md`。

**布局：变体 A「顶部状态带」**，再从变体 C 借用十字线读数。

- 首屏三栏：负荷头条（ATL/CTL > 1.5 时标题变红，写成"负荷突增：ATL 是 CTL 的 1.6 倍"，下面一句建议），CTL/ATL/TSB 三个大数字，近 12 周 CTL/ATL 曲线加 TSB 柱；周跑量（本周、上周、滚动 7 天，近 12 周柱状图，本周未完的柱子用灰色）；成绩预测表（VDOT 为主，Riegel 和 Garmin 两列对照，下面写明依据）。
- 第二屏是全宽的有氧能力趋势：纵轴是参考心率下的配速，越快越高；点表示每周中位数，线是 4 周滚动中位数，虚线标出比赛；可以切换半年、1 年、2 年、全部；下面是每周平均温度副图。鼠标悬停显示十字线，读出那一周的日期、配速和温度。
- 最下面两张表：长距离（60 分钟以上）的 EF 和 decoupling，超过 5% 标红；最近的比赛（来自 `races.csv`）。
- 每块旁边有"负荷怎么算的""跑量怎么算的""有氧能力怎么算的""预测怎么算的"，点开显示公式和参数。
- 变体 B（侧栏分页）要点几下才能看全；C（五个面板共用时间轴）适合找关联，但首屏回答不了"这周该怎么练"。这两个都没选。

**三种状态**：

- 还没同步：显示"还没有数据"，列出 `runsync sync` 和 `runsync login` 的步骤，以及数据目录位置。
- 预测过期（6 个月内没有比赛）：预测表变淡，用红字说明最近一场比赛的日期，提示去更新 `races.csv`。
- 有效跑步少于 2 次的周：有氧能力的点留空，不插值。

**技术栈：FastAPI 加静态前端**，不用 Streamlit，也不用 Tauri。

- Streamlit 对照版用同样的数据重做了变体 A。整体效果大约能还原七八成，十字线用 Altair 的 `selection_point` 可以原生实现。但几处细节做不到：多行的编辑式批注（Vega-Lite 只能放单行文字）；上下叠放的图表左边对不齐（各图纵轴宽度不同）；字体、标题颜色、红点、表格线都要写 CSS 去改 Streamlit 内部的 DOM。全局改字体之后，展开框的图标直接显示成 `_arrow_right` 文字，说明这种 CSS 很脆，升级 Streamlit 就可能失效。另外 Streamlit 会带进 pandas 和 pyarrow，而 [项目骨架与依赖](11-project-skeleton.md) 定的是不依赖 pandas。
- Tauri 需要 Rust 工具链和打包，还要多一层窗口外壳。这个仪表盘只在本机浏览器里用，不需要。
- FastAPI 只做一件事：调用 `analysis/src/running/` 计算，以 JSON 返回；分析库只读打开。前端就是 HTML 原型的正式版：原生 ES modules 加手写 SVG（原型里的 `chart()` 证明这条路可行），不用 node 构建。字体改成本地托管，不走 Google Fonts。
- 服务只绑定 `127.0.0.1`。Streamlit 默认监听所有网卡，原型运行时就暴露过局域网地址。
- 实施不在本地图内。
