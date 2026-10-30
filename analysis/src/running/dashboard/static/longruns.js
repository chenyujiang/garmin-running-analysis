// Long-run table (ticket 13). Reads GET /api/long-runs.
// Prototype variant A: a plain table in the lower two-column row (column 1),
// decoupling above the limit in red, plus a "how is this calculated" note.

import { h, fmtDate } from "./dom.js";

const TITLE = "长距离的心率漂移";

/** The section element; it fills itself once the data arrives. */
export function longRunsSection() {
  const section = h("section", { class: "lower-longruns" }, head(), h("p", { class: "small muted" }, "正在读取…"));
  load(section);
  return section;
}

function head() {
  return h("div", { class: "sec-head" }, h("h2", {}, TITLE), h("span", { class: "muted small" }, "60 分钟以上的跑步"));
}

async function load(section) {
  const today = new URLSearchParams(location.search).get("today");
  let v;
  try {
    const r = await fetch(today ? `api/long-runs?today=${encodeURIComponent(today)}` : "api/long-runs");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    v = await r.json();
  } catch (err) {
    section.replaceChildren(head(), h("p", { class: "warn" }, `无法读取长距离：${err.message}`));
    return;
  }
  section.replaceChildren(head(), ...render(v));
}

const pad = (n) => String(n).padStart(2, "0");

function fmtDur(s) {
  const t = Math.round(s);
  const hh = Math.floor(t / 3600);
  const mm = Math.floor((t % 3600) / 60);
  return hh ? `${hh}:${pad(mm)}:${pad(t % 60)}` : `${mm}:${pad(t % 60)}`;
}

function render(v) {
  const limit = v.method.params.decoupling_limit_pct;
  const body = v.runs.length
    ? table(v.runs)
    : h("p", { class: "small muted" }, "还没有 60 分钟以上的跑步。");
  return [
    body,
    h("div", { class: "foot" },
      h("span", { class: "small muted" }, `decoupling 超过 ${limit}% 标红：后半程同配速下心率明显漂高。`),
      how(v.method),
    ),
  ];
}

function table(runs) {
  return h("table", {},
    h("thead", {}, h("tr", {},
      h("th", {}, "日期"),
      h("th", { class: "r" }, "距离"),
      h("th", { class: "r" }, "时长"),
      h("th", { class: "r", title: "m/min ÷ bpm" }, "EF"),
      h("th", { class: "r" }, "decoupling"),
    )),
    h("tbody", {}, ...runs.map(row)),
  );
}

function row(r) {
  const dec = r.decoupling_pct;
  return h("tr", {},
    h("td", {}, fmtDate(r.start_time_local)),
    h("td", { class: "r" }, r.distance_m == null ? "—" : `${(r.distance_m / 1000).toFixed(1)} km`),
    h("td", { class: "r" }, fmtDur(r.duration_s)),
    h("td", { class: "r" }, r.ef == null ? "—" : r.ef.toFixed(2)),
    h("td", { class: r.decoupling_high ? "r dec-high" : "r" }, dec == null ? "—" : `${dec.toFixed(1)}%`),
  );
}

function how(method) {
  const p = method.params;
  return h("details", { class: "how" },
    h("summary", {}, "怎么算的"),
    h("div", { class: "body" },
      h("p", {}, method.description),
      h("p", { class: "muted" },
        `当前参数：长距离 ≥ ${p.min_duration_s / 60} 分钟，热身 ${p.warmup_s / 60} 分钟，`
        + `稳态至少 ${p.min_steady_s / 60} 分钟，标红阈值 ${p.decoupling_limit_pct}%，EF 单位 ${p.ef_unit}。`),
    ),
  );
}
