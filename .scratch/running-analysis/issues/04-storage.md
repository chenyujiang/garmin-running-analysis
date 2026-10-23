# 存储方案

Type: grilling
Status: open
Blocked by: 01, 03

## Question

拉下来的数据存成什么样？

- 原始 FIT / JSON 是否原样保留（作为可重放的事实来源）。
- 分析用存储选哪个：SQLite、DuckDB、Parquet 文件，还是组合。
- 逐秒数据流和汇总数据、健康数据分别怎么组织。
- 存储格式要能由 Rust 导入 CLI 写入、由 Python 分析读取：两边库的支持程度，以及 schema 由哪一边定义。
