# 05: 每日汇总同步

**What to build:** `runsync sync` 同时拉取每日汇总（静息心率等），写进原始档案和分析库。每次都重拉最近 7 天，接住当天不完整的数据和 Garmin 事后的修正。

**Blocked by:** 04（Personal API 活动同步）

**Status:** done

来源：[实施 spec](../spec.md)，User Story 15。

- [x] 每日汇总按 7 天一个区间请求，每天一个 JSON 文件存进原始档案
- [x] 回填从 2021-08 开始；之后每次同步重拉最近 7 天，覆盖同名文件
- [x] `daily_wellness` 每天一行，用 upsert 写入；`rebuild` 也能从原始档案重建这张表
- [x] HRV 和睡眠的空响应只留在原始档案里，不建表
- [x] Seam 1 测试：同一天重复写入时是 upsert
- [x] Seam 2 测试：最近 7 天的每日汇总被覆盖，更早的不重拉

## 结论

- **接口**：`GET /usersummary-service/v2/dailysummaries?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD`（闭区间，取自官方 `garmin-connect-personal-api-python` 1.0.0 的 `get_daily_summaries`），响应 `{"data": [...]}`，每个有数据的日子一行。`ActivitySource` 新增 `daily_summaries(start, end) -> String`。
- **原始档案**：`raw/personal_api/daily_summaries/<YYYY-MM-DD>.json`，内容是响应里那一天的行，原样保存（`RawValue`，不重排字段）。请求了但没有数据的日子写 `null`，这样续传时不会反复去拉 2021-08 到 2021-10 这段空白。
- **顺序**：活动同步之后再拉每日汇总（活动被限流就不拉）。先重拉最近 7 天 `today-6..today`（`today` 是本机时区的日期，`SyncOptions.today`），再从 `today-13..today-7` 起每 7 天一段往回补到 2021-08-01，新的在前；一段里每天的文件都在就跳过。限流或出错时停下，已写的文件和行保留，`sync_runs` 记相应 outcome。
- **`daily_wellness`**（迁移 `0004`）：`calendar_date` 主键，`INSERT OR REPLACE`。列：静息/最低/最高心率、步数和步行距离、总/活动/静息卡路里、中高强度分钟、平均压力、Body Battery 最低/最高、平均呼吸率。数值按原样存（整数存 INTEGER，小数存 REAL），缺字段为 NULL。`null` 日不建行。
- **HRV 和睡眠**：不单独请求、不建表。spec 的原始档案布局只列了 `daily_summaries/`；用户晚上不戴表，HRV/睡眠没有数据（spec「不做」一节），单独回填会让请求量翻三倍。每日汇总的整行 JSON 已原样存档，以后需要可从档案里取。
- **rebuild**：从 `daily_summaries/*.json` 重建 `daily_wellness`；坏文件计入 skipped；stdout 增加 `N daily summaries`。
- 测试：Seam 2 `importer/tests/daily_sync.rs`（6 个），Seam 1 `tests/rebuild.rs` 新增 2 个（rebuild 载入、同一天重复写入是 upsert）。首次回填约 270 个请求，耗时取决于 `personal_api_interval_s`。
