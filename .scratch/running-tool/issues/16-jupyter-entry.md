# 16: Jupyter 探索入口

**What to build:** 用户用 `uv run jupyter lab` 打开一个示例 notebook，调用和仪表盘同一套公开函数，查看有氧能力、负荷和周跑量，并在此基础上深入探索。

**Blocked by:** 11（有氧能力的计算与接口）

**Status:** ready-for-agent

来源：[实施 spec](../spec.md)，User Stories 47、48。

- [ ] `jupyterlab` 在 Python 项目的 dev 依赖组里
- [ ] 示例 notebook 只调用分析包的公开函数，不复制计算逻辑
- [ ] 提交时 `nbstripout` 清掉输出，确认 git 里的 notebook 不含个人数据
- [ ] README 写明怎么启动 Jupyter，以及在 VS Code 里怎么选内核
