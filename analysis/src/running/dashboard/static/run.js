// Activity detail page, #/run/<id> (run-detail tickets 02-07).
// Reads GET /api/activities/<id> once; every section renders from that body.
//
// Each section is one renderer `(detail) => Node | null` in RENDERERS, in page
// order, with its code in its own block below. Later tickets add one line in
// their slot of RENDERERS and their functions in their block.

import { h, fmtDate } from "./dom.js";
import { typeName } from "./runs.js";

/** The detail page; fills itself once the data arrives. */
export function runPage(id) {
  const section = h("section", { class: "run" }, back(), h("p", { class: "small muted" }, "正在读取…"));
  load(section, id);
  return section;
}

function back() {
  return h("p", { class: "small" }, h("a", { href: "#/runs" }, "← 全部活动"));
}

async function load(section, id) {
  let v;
  try {
    const r = await fetch(`api/activities/${encodeURIComponent(id)}`);
    if (r.status === 404) {
      const body = await r.json().catch(() => ({}));
      section.replaceChildren(back(), notFound(id, body.detail));
      return;
    }
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    v = await r.json();
  } catch (err) {
    section.replaceChildren(back(), h("p", { class: "warn" }, `无法读取活动详情：${err.message}`));
    return;
  }
  section.replaceChildren(back(), headline(v.activity), ...RENDERERS.map((render) => render(v)).filter(Boolean));
}

function notFound(id, detail) {
  return h("div", { class: "empty" },
    h("h1", { class: "headline" }, "找不到这个活动"),
    h("p", { class: "dek" }, detail || `没有编号为 ${id} 的活动。`),
    h("p", { class: "small muted" }, "收藏的链接可能已经过期，或者分析库重建后这个活动不在了。回到 ",
      h("a", { href: "#/runs" }, "全部活动"), " 重新找。"),
  );
}

function headline(a) {
  return h("header", { class: "run-head" },
    h("p", { class: "small muted" },
      `${fmtDate(a.start_time_local)} ${a.start_time_local.slice(11, 16)} · ${typeName(a.activity_type)}`),
    h("h1", { class: "headline" }, a.activity_name || "（未命名）"),
  );
}

// Shared formatting.

const pad = (n) => String(n).padStart(2, "0");

export function fmtDur(s) {
  const t = Math.round(s);
  const hh = Math.floor(t / 3600);
  const mm = Math.floor((t % 3600) / 60);
  return hh ? `${hh}:${pad(mm)}:${pad(t % 60)}` : `${mm}:${pad(t % 60)}`;
}

export function fmtPace(s) {
  const t = Math.round(s);
  return `${Math.floor(t / 60)}:${pad(t % 60)}`;
}

export function how(method) {
  return h("details", { class: "how" },
    h("summary", {}, "怎么算的"),
    h("div", { class: "body" }, h("p", {}, method.description)),
  );
}

// --- summary (ticket 02) -----------------------------------------------------

function summarySection(v) {
  const s = v.summary;
  const missing = (key) => s.unavailable[key] ?? "—";
  const value = (key, fmt) => (s[key] == null ? missing(key) : fmt(s[key]));
  const item = (label, key, fmt, title) =>
    h("div", title ? { title } : {},
      h("span", { class: "l" }, label),
      h("span", { class: s[key] == null ? "num muted" : "num" }, value(key, fmt)));
  return h("section", { class: "run-summary" },
    h("div", { class: "sec-head" }, h("h2", {}, "概要"), h("div", { class: "tools" }, how(s.method))),
    h("div", { class: "stat-line" },
      item("距离", "distance_m", (m) => `${(m / 1000).toFixed(2)} km`),
      item("时长", "duration_s", fmtDur),
      item("跑步配速", "running_pace_s_per_km", (p) => `${fmtPace(p)} /km`, "只算跑的秒，走路不计"),
      item("Garmin 平均配速", "garmin_pace_s_per_km", (p) => `${fmtPace(p)} /km`, "含走路，仅作参照"),
      item("平均心率", "avg_hr_bpm", (b) => `${Math.round(b)} bpm`),
      item("最大心率", "max_hr_bpm", (b) => `${Math.round(b)} bpm`),
      item("平均步频", "avg_cadence_spm", (c) => `${Math.round(c)} spm`, "只算跑的秒"),
      item("累计爬升", "elevation_gain_m", (m) => `${Math.round(m)} m`),
      item("气温", "air_temperature_c", (c) => `${c.toFixed(1)} °C`, "Open-Meteo，活动中点时刻"),
    ),
  );
}

// --- per-second series (ticket 03) -------------------------------------------


// --- splits: laps and kilometres (ticket 04) ---------------------------------

function splitsSection(v) {
  const s = v.splits;
  if (!s) return null;
  return h("section", { class: "run-splits" },
    h("div", { class: "sec-head" }, h("h2", {}, "分段"), h("div", { class: "tools" }, how(s.method))),
    h("h3", {}, "每公里"),
    s.kilometres == null
      ? h("p", { class: "small muted" }, s.unavailable.kilometres ?? "—")
      : splitKmTable(s.kilometres),
    h("h3", {}, "手表的圈"),
    s.laps.length ? splitLapTable(s.laps) : h("p", { class: "small muted" }, s.unavailable.laps ?? "—"),
  );
}

const splitCell = (x, fmt) => h("td", { class: x == null ? "r muted" : "r" }, x == null ? "—" : fmt(x));
const splitKm = (m) => `${(m / 1000).toFixed(2)} km`;
const splitPace = (p) => `${fmtPace(p)} /km`;
const splitBpm = (b) => `${Math.round(b)}`;
const splitSpm = (c) => `${Math.round(c)}`;
const splitMetres = (m) => `${Math.round(m)}`;
const splitNum = { style: "font-variant-numeric: tabular-nums" };

function splitKmTable(rows) {
  return h("table", { class: "km-table", ...splitNum },
    h("thead", {}, h("tr", {},
      h("th", {}, "公里"),
      h("th", { class: "r" }, "时长"),
      h("th", { class: "r", title: "只算跑的秒，走路不计" }, "跑步配速"),
      h("th", { class: "r", title: "按坡度换算成平路的配速" }, "GAP 配速"),
      h("th", { class: "r" }, "心率"),
      h("th", { class: "r", title: "只算跑的秒" }, "步频"),
      h("th", { class: "r" }, "升 m"),
      h("th", { class: "r" }, "降 m"),
    )),
    h("tbody", {}, ...rows.map((k) => h("tr", {},
      h("td", {}, k.partial ? `${k.km}（${splitKm(k.distance_m)}）` : `${k.km}`),
      splitCell(k.duration_s, fmtDur),
      splitCell(k.running_pace_s_per_km, splitPace),
      splitCell(k.gap_pace_s_per_km, splitPace),
      splitCell(k.avg_hr_bpm, splitBpm),
      splitCell(k.avg_cadence_spm, splitSpm),
      splitCell(k.elevation_gain_m, splitMetres),
      splitCell(k.elevation_loss_m, splitMetres),
    ))),
  );
}

function splitLapTable(rows) {
  return h("table", { class: "lap-table", ...splitNum },
    h("thead", {}, h("tr", {},
      h("th", {}, "圈"),
      h("th", { class: "r" }, "距离"),
      h("th", { class: "r", title: "计时时长，不含暂停" }, "时长"),
      h("th", { class: "r", title: "手表记录的圈平均配速" }, "配速"),
      h("th", { class: "r" }, "心率"),
      h("th", { class: "r" }, "最大心率"),
      h("th", { class: "r" }, "步频"),
      h("th", { class: "r" }, "升 m"),
      h("th", { class: "r" }, "降 m"),
    )),
    h("tbody", {}, ...rows.map((l) => h("tr", {},
      h("td", {}, `${l.lap}`),
      splitCell(l.distance_m, splitKm),
      splitCell(l.duration_s, fmtDur),
      splitCell(l.pace_s_per_km, splitPace),
      splitCell(l.avg_hr_bpm, splitBpm),
      splitCell(l.max_hr_bpm, splitBpm),
      splitCell(l.avg_cadence_spm, splitSpm),
      splitCell(l.elevation_gain_m, splitMetres),
      splitCell(l.elevation_loss_m, splitMetres),
    ))),
  );
}


// --- route shape (ticket 05) -------------------------------------------------


// --- run metrics (ticket 06) -------------------------------------------------


// --- report (ticket 07) ------------------------------------------------------


// --- section registry --------------------------------------------------------
// Page order. Each ticket adds its renderer on the line below its own comment;
// the comment lines between the slots keep parallel edits apart.

const RENDERERS = [
  // report (ticket 07)
  summarySection,
  // series (ticket 03)
  // splits (ticket 04)
  splitsSection,
  // route (ticket 05)
  // metrics (ticket 06)
];
