// Dashboard entry point. Native ES module, no build step.
// Reads GET /api/status, then renders the page the hash names:
//   #/ (or no hash)  home: the empty state or the data summary
//   #/runs?...       activity list (runs.js)
//   #/run/<id>       activity detail (placeholder until the detail ticket)
// Without an analysis database every page shows the empty state.

import { h, fmtDateTime, fmtDate } from "./dom.js";
import { aerobicSection } from "./aerobic.js";
import { markAllReadButton } from "./changes.js";
import { loadSection } from "./load.js";
import { longRunsSection } from "./longruns.js";
import { predictionsSection } from "./predictions.js";
import { racesSection } from "./races.js";
import { runsPage } from "./runs.js";
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
  render(status, parseRoute(location.hash));
}

/** "#/runs?type=all" -> { name: "runs", query }; unknown hashes go home. */
export function parseRoute(hash) {
  const raw = hash.replace(/^#\/?/, "");
  const [path, search = ""] = raw.split("?", 2);
  const query = new URLSearchParams(search);
  if (path === "runs") return { name: "runs", query };
  const m = /^run\/(\d+)$/.exec(path);
  if (m) return { name: "run", id: m[1], query };
  return { name: "home", query };
}

function page(s, route) {
  if (!s.has_data) return empty(s);
  if (route.name === "runs") return runsPage(route.query);
  if (route.name === "run") return runPlaceholder(route.id);
  return summary(s);
}

function runPlaceholder(id) {
  return h("section", {},
    h("p", { class: "small" }, h("a", { href: "#/runs" }, "← 全部活动")),
    h("h1", { class: "headline" }, `活动 ${id}`),
    h("p", { class: "dek" }, "详情页还在做。"),
  );
}

function render(s, route) {
  syncLine.replaceChildren(...[
    s.has_data ? markAllReadButton() : null,
    h("span", {}, s.has_data
      ? `最近同步 ${s.last_sync_utc ? fmtDateTime(s.last_sync_utc) : "未知"}`
      : "尚未同步"),
  ].filter(Boolean));
  const warning = s.config_error ? h("p", { class: "warn" }, s.config_error) : null;
  main.replaceChildren(...[warning, page(s, route)].filter(Boolean));
  document.querySelectorAll(".topnav a").forEach((a) => {
    const here = parseRoute(a.getAttribute("href")).name === route.name;
    if (here) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  window.scrollTo(0, 0);
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
    predictionsSection(),
  );
}

// Lower row, prototype variant A: long runs (column 1) | recent races (column 2).
function lower() {
  return h("div", { class: "a-lower" },
    longRunsSection(),
    racesSection(),
  );
}

function summary(s) {
  return h("div", {}, band(), aerobicSection(), lower(), overview(s));
}

function overview(s) {
  return h("section", {},
    h("h1", { class: "headline" }, `已有 ${s.activity_count} 个活动`),
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

window.addEventListener("hashchange", load);
load();
