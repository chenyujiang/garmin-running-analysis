// Recent races table (ticket 14), lower row column 2. Reads GET /api/races.

import { h, fmtDate } from "./dom.js";
import { fmtDistance, fmtTime } from "./predictions.js";

const TITLE = "最近比赛";
const LIMIT = 10;

/** The section element; it fills itself once the data arrives. */
export function racesSection() {
  const section = h("section", { class: "lower-races" }, head(), h("p", { class: "small muted" }, "正在读取…"));
  load(section);
  return section;
}

function head() {
  return h("div", { class: "sec-head" }, h("h2", {}, TITLE), h("span", { class: "muted small" }, "来自 races.csv"));
}

async function load(section) {
  const today = new URLSearchParams(location.search).get("today");
  let v;
  try {
    const r = await fetch(today ? `api/races?today=${encodeURIComponent(today)}` : "api/races");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    v = await r.json();
  } catch (err) {
    section.replaceChildren(head(), h("p", { class: "warn" }, `无法读取比赛：${err.message}`));
    return;
  }
  section.replaceChildren(head(), ...render(v));
}

/** No races.csv yet: one short line; how to add it folds away. */
function missingHint() {
  return [
    h("p", { class: "small muted" }, "还没有比赛记录。"),
    h("details", { class: "how" },
      h("summary", {}, "怎么添加"),
      h("div", { class: "body" },
        h("p", {}, "在数据目录新建 ", h("code", {}, "races.csv"), "，第一行写列名，每场比赛一行："),
        h("pre", {}, "date,activity_id,distance_m,time_s,all_out,note\n2026-03-01,,5000,1260,yes,parkrun"))),
  ];
}

const pace = (s) => `${Math.floor(Math.round(s) / 60)}:${String(Math.round(s) % 60).padStart(2, "0")}`;

function render(v) {
  // A missing races.csv is normal until the first race: grey hint, not an error.
  if (v.races_error?.kind === "missing") return missingHint();
  if (v.races_error) return [h("p", { class: "warn small" }, v.races_error.message)];
  if (!v.races.length) return [h("p", { class: "small muted" }, "races.csv 里还没有比赛。")];
  return [
    h("table", {},
      h("thead", {}, h("tr", {},
        h("th", {}, "日期"),
        h("th", {}, "距离"),
        h("th", { class: "r" }, "成绩"),
        h("th", { class: "r" }, "配速"),
        h("th", { class: "r" }, "VDOT"),
        h("th", {}, "备注"),
      )),
      h("tbody", {}, ...v.races.slice(0, LIMIT).map((r) => h("tr", { class: r.all_out ? "" : "soft" },
        h("td", {}, r.activity_id == null ? fmtDate(r.date) : h("a", { href: `#/run/${r.activity_id}` }, fmtDate(r.date))),
        h("td", {}, fmtDistance(r.distance_m)),
        h("td", { class: "r" }, fmtTime(r.time_s)),
        h("td", { class: "r" }, `${pace(r.pace_s_per_km)} /km`),
        h("td", { class: "r" }, r.vdot.toFixed(1)),
        h("td", {}, r.all_out ? r.note : `${r.note ? `${r.note}；` : ""}非全力`),
      ))),
    ),
    h("p", { class: "small muted" }, "灰色行不是全力比赛，不参与预测。"),
  ];
}
