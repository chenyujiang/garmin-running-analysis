# 16: Jupyter 探索入口

**What to build:** 用户用 `uv run jupyter lab` 打开一个示例 notebook，调用和仪表盘同一套公开函数，查看有氧能力、负荷和周跑量，并在此基础上深入探索。

**Blocked by:** 11（有氧能力的计算与接口）

**Status:** done

来源：[实施 spec](../spec.md)，User Stories 47、48。

- [x] `jupyterlab` 在 Python 项目的 dev 依赖组里
- [x] 示例 notebook 只调用分析包的公开函数，不复制计算逻辑
- [x] 提交时 `nbstripout` 清掉输出，确认 git 里的 notebook 不含个人数据
- [x] README 写明怎么启动 Jupyter，以及在 VS Code 里怎么选内核

## 结论

- `jupyterlab` 和 `nbstripout` 在 ticket 02 时已放进 `analysis/pyproject.toml` 的 dev 组；`.gitattributes` 的 nbstripout 过滤器也已就位。
- 示例 notebook：`analysis/notebooks/explore.ipynb`。依次看数据状态、周跑量（`weekly_volume`）、训练负荷（`training_load`）、有氧能力（`aerobic_trend`）、每次跑步表（`running_summaries`、`aerobic_runs`），最后用 `load_records` + `steady_state` 看单次路跑的逐秒稳态段和 EF。没有数据库时每一格也能跑完，只显示空表。
- 测试 `analysis/tests/test_notebook.py`：用 `nbclient` 在临时 `RUNNING_DATA_DIR`（合成路跑）和"还没有数据库"两种情况下把 notebook 从头跑到尾，不能有报错；静态检查代码格只从 `running` 导入公开名字、不访问 `_` 开头的属性、不直接用 `duckdb`/`sqlite3`；提交的 notebook 没有输出、`execution_count` 为空。
- README 的 Notebooks 一节写了 `uv run jupyter lab notebooks/explore.ipynb` 和 VS Code 选 `analysis\.venv` 内核的步骤。
- notebook 不画图：分析包没有绘图依赖，表格用 polars 自带的 HTML 显示。以后要画图再决定加 altair 还是别的。
