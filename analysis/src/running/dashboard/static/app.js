// Dashboard entry point. Native ES module, no build step.
// Reads GET /api/status and renders either the empty state or the data summary.

import { h, fmtDateTime, fmtDate } from "./dom.js";
import { loadSection } from "./load.js";
import { volumeSection } from "./volume.js";

const main = document.getElementById("main");
const syncLine = document.getElementById("sync-line");

async function load() {
  let status;
  try {
    const r = await fetch("api/status");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    status = await r.json();
  } catch (err) {
    syncLine.replaceChildren(h("span", {}, "读取失败"));
    main.replaceChildren(h("p", { class: "warn" }, `无法读取数据状态：${err.message}`));
    return;
  }
  render(status);
}

function render(s) {
  syncLine.replaceChildren(
    h("span", {}, s.has_data
      ? `最近同步 ${s.last_sync_utc ? fmtDateTime(s.last_sync_utc) : "未知"}`
      : "尚未同步"),
  );
  const warning = s.config_error ? h("p", { class: "warn" }, s.config_error) : null;
  main.replaceChildren(...[warning, s.has_data ? summary(s) : empty(s)].filter(Boolean));
}

function empty(s) {
  return h("div", { class: "empty" },
    h("h1", { class: "headline" }, "还没有数据"),
    h("p", { class: "dek" }, "仪表盘读的是分析库 ", h("code", {}, "running.sqlite"), "，现在里面还没有活动。"),
    h("ol", {},
      h("li", {}, "在终端运行 ", h("code", {}, "runsync sync"),
        "。第一次运行会回填全部历史，时间较长，可以中途打断，再次运行会接着拉。"),
      h("li", {}, "Garmin 的三项参照指标需要先运行一次 ", h("code", {}, "runsync login"), "。"),
      h("li", {}, "同步完成后刷新本页。"),
    ),
    dataDirNote(s),
  );
}

// Top status band, prototype variant A: load | weekly volume | predictions.
// Each column is its own module and places itself with a grid-column rule.
function band() {
  return h("div", { class: "a-band" },
    loadSection(),
    volumeSection(),
  );
}

function summary(s) {
  return h("div", {}, band(), overview(s));
}

function overview(s) {
  return h("section", {},
    h("h1", { class: "headline" }, `已有 ${s.activity_count} 个活动`),
    h("p", { class: "dek" }, "各项分析会在后续版本里陆续出现在这里。"),
    h("div", { class: "stat-line" },
      stat("活动", h("span", { class: "big" }, String(s.activity_count))),
      stat("最近一次同步", h("span", { class: "num" }, s.last_sync_utc ? fmtDateTime(s.last_sync_utc) : "未知")),
      stat("最近一次活动", h("span", { class: "num" }, s.latest_activity_local ? fmtDate(s.latest_activity_local) : "—")),
    ),
    dataDirNote(s),
  );
}

function stat(label, value) {
  return h("div", {}, h("span", { class: "l" }, label), value);
}

function dataDirNote(s) {
  return h("p", { class: "small muted" },
    "数据目录：", h("code", {}, s.data_dir), "（由 ", h("code", {}, "RUNNING_DATA_DIR"), " 指定）");
}

load();
