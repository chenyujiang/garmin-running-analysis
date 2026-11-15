# Design of the analysis dashboard

Type: prototype
Status: resolved
Blocked by: none

## Question

How should the three core analyses (long-term aerobic fitness trend, weekly volume and training load, race prediction) be presented in a local dashboard?

- Design with `impeccable`: information hierarchy, layout, chart types, colours and fonts, empty state (before data has been synced).
- Build a rough interactive prototype (static data is fine) to see the effect before settling details.
- The prototype must answer whether a ready-made framework like Streamlit can reach this design, or whether we need our own frontend. That decides the tech stack.

The exact metric formulas are not decided yet (see [Definition of the aerobic fitness metric](06-aerobic-metric.md) and [Training load model and race prediction method](07-load-and-prediction.md)); the prototype uses illustrative data first.

## Comments

- 2026-10-23: the metrics to show are now decided, see [Definition of the aerobic fitness metric](06-aerobic-metric.md) and [Training load model and race prediction method](07-load-and-prediction.md): weekly aerobic fitness trend (with weekly mean temperature), EF, decoupling; CTL/ATL/TSB and the "负荷突增" (load spike) hint; weekly volume; predictions per distance (including the "过期" (stale) state and the Garmin reference value).
- 2026-10-23 (from [Project skeleton and dependencies](11-project-skeleton.md)): the computation lives in the `analysis/src/running/` package and the dashboard reuses it directly. The analysis side uses polars and DuckDB, with no pandas dependency; the analysis database is `running.sqlite` in the data directory, opened read-only.

## Answer

Decided on 2026-10-23 after looking at the prototype. The prototype is on the throwaway branch `prototype/dashboard` (commit `8013fab`), not merged into main: `.scratch/running-analysis/prototype/dashboard.html` is the static HTML prototype, and `streamlit/app.py` the Streamlit comparison version. Both use synthetic data. To view: `git worktree add ../garmin-proto prototype/dashboard`, then open `dashboard.html?variant=A` in a browser.

**Visual direction**: data graphics from a newspaper sports section. Newsprint-coloured background, ink-black text, red used only for annotations and warnings; headings in a serif face (Noto Serif SC), body text and numbers in IBM Plex Sans + Noto Sans SC, numbers with tabular-nums. At most 2 editorial annotations per chart. Numbers that changed since the last visit get a red dot, and one click can "全部标为已读" (mark all as read). Product background and priorities are in `PRODUCT.md` at the repository root.

**Layout: variant A, "top status band"**, borrowing the crosshair readout from variant C.

- First screen, three columns: the load headline (when ATL/CTL > 1.5 the heading turns red and reads "负荷突增：ATL 是 CTL 的 1.6 倍" (load spike: ATL is 1.6 times CTL), with one line of advice below), the three big numbers CTL/ATL/TSB, and CTL/ATL curves with TSB bars for the last 12 weeks; weekly volume (this week, last week, rolling 7 days, a bar chart of the last 12 weeks, with this week's unfinished bar in grey); the prediction table (VDOT as main, Riegel and Garmin as two comparison columns, with the basis written below).
- The second screen is the full-width aerobic fitness trend: the y axis is pace at the reference heart rate, faster is higher; dots are weekly medians, the line the 4-week rolling median, dashed lines mark races; switchable between half a year, 1 year, 2 years and all; below it, a secondary chart of weekly mean temperature. Hovering shows a crosshair reading that week's date, pace and temperature.
- Two tables at the bottom: EF and decoupling of long runs (60 minutes or more), red above 5%; recent races (from `races.csv`).
- Each block has "负荷怎么算的" (how load is computed), "跑量怎么算的" (how volume is computed), "有氧能力怎么算的" (how aerobic fitness is computed), "预测怎么算的" (how predictions are computed), which expand to show formulas and parameters.
- Variant B (sidebar pages) needs several clicks to see everything; C (five panels on a shared time axis) is good for finding correlations but its first screen does not answer "how should I train this week". Neither was chosen.

**Three states**:

- Not synced yet: show "还没有数据" (no data yet), listing the `runsync sync` and `runsync login` steps and the data directory location.
- Prediction stale (no race in 6 months): the prediction table fades, a red note gives the date of the latest race and suggests updating `races.csv`.
- Weeks with fewer than 2 valid runs: the aerobic fitness point stays empty, with no interpolation.

**Tech stack: FastAPI plus a static frontend**, neither Streamlit nor Tauri.

- The Streamlit comparison version rebuilt variant A with the same data. Overall it reproduces about 70–80% of the effect, and the crosshair can be done natively with Altair's `selection_point`. But some details are out of reach: multi-line editorial annotations (Vega-Lite only takes single-line text); stacked charts do not align on the left (each chart's y axis has a different width); fonts, heading colour, red dots and table rules all need CSS that reaches into Streamlit's internal DOM. After changing the font globally, the expander icon showed up as the literal text `_arrow_right`, which shows how brittle that CSS is; a Streamlit upgrade could break it. Streamlit also pulls in pandas and pyarrow, while [Project skeleton and dependencies](11-project-skeleton.md) decided against depending on pandas.
- Tauri needs the Rust toolchain and packaging, plus an extra window shell. This dashboard is only used in a local browser and does not need it.
- FastAPI does one thing: call the computations in `analysis/src/running/` and return JSON; the analysis database is opened read-only. The frontend is the production version of the HTML prototype: native ES modules plus hand-written SVG (the prototype's `chart()` shows this works), with no node build. Fonts are self-hosted instead of using Google Fonts.
- The server binds only to `127.0.0.1`. Streamlit listens on all interfaces by default, and the prototype did expose a LAN address while running.
- Implementation is outside this map.
