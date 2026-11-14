// Auckland parkrun courses, #/parkruns?target=20:00. Reads GET /api/parkruns:
// every course's 5 km elevation profile, climbs, even-effort splits for a flat
// 5K target time and pacing advice. Courses come easiest first (least climb).

import { h, fmtDur, fmtPace } from "./dom.js";
import { parseTime } from "./plan.js";
import { how } from "./run.js";
import { chart, niceStep, ticks } from "./svg.js";

const TAG_CLASS = { "平路": "flat", "微起伏": "rolling", "起伏": "hilly", "多坡": "steep" };

export function parkrunsPage(query) {
  const root = h("div", { class: "parkruns" }, h("p", { class: "loading" }, "正在读取 parkrun 路线…"));
  load(root, query);
  return root;
}

async function load(root, query) {
  const params = new URLSearchParams();
  const target = parseTime(query.get("target"));
  if (target) params.set("target_s", String(target));
  let r;
  try {
    const res = await fetch(`api/parkruns?${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    r = await res.json();
  } catch (err) {
    root.replaceChildren(h("p", { class: "warn" }, `无法读取 parkrun 路线：${err.message}`));
    return;
  }
  root.replaceChildren(...render(r));
}

const pct = (g) => `${(g * 100).toFixed(1)}%`;
const signed = (s) => `${s >= 0 ? "+" : "−"}${Math.abs(Math.round(s))} 秒`;
const metres = (m) => `${m >= 0 ? "+" : "−"}${Math.abs(m).toFixed(0)} m`;
const anchor = (slug) => `pr-${slug}`;

function render(r) {
  return [
    h("header", { class: "plan-head" },
      h("h1", { class: "headline" }, "奥克兰 parkrun 路线"),
      h("p", { class: "dek" },
        `奥克兰地区 ${r.courses.length} 个 parkrun，按累计爬升从少到多排列。`
        + "每条路线给出高程图、按均匀用力分配的每公里配速和跑法建议。"),
      form(r),
      h("div", { class: "tools" }, how(r.method))),
    summaryTable(r),
    ...r.courses.map((c) => courseSection(c, r.target_s)),
    h("p", { class: "small muted" }, `数据来源：${r.source}。`),
  ];
}

function form(r) {
  const tgt = h("input", { name: "target", size: "6", value: fmtDur(r.target_s), inputmode: "numeric" });
  const f = h("form", { class: "plan-form small" },
    h("label", {}, "平路 5K 目标 ", tgt),
    h("button", { type: "submit" }, "重新计算"),
    h("span", { class: "muted" }, "各路线的预计用时和每公里配速按这个平路成绩、同样用力折算。"));
  f.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = new URLSearchParams();
    if (parseTime(tgt.value)) q.set("target", tgt.value.trim());
    location.hash = `#/parkruns?${q}`;
  });
  return f;
}

function tagChip(tag) {
  return h("span", { class: `pr-tag pr-${TAG_CLASS[tag] ?? "flat"}` }, tag);
}

function summaryTable(r) {
  const jump = (c) => {
    const a = h("a", { href: `#${anchor(c.slug)}` }, c.name);
    a.addEventListener("click", (e) => {
      e.preventDefault();
      document.getElementById(anchor(c.slug))?.scrollIntoView({ behavior: "smooth" });
    });
    return a;
  };
  return h("section", { class: "pr-summary" },
    h("div", { class: "sec-head" }, h("h2", {}, "总览")),
    h("table", {},
      h("thead", {}, h("tr", {},
        h("th", {}, "parkrun"), h("th", {}, "地区"), h("th", {}, "类型"),
        h("th", { class: "r" }, "累计爬升"), h("th", { class: "r" }, "高差"),
        h("th", { class: "r" }, "最陡 100 m"), h("th", { class: "r" }, "预计用时"),
        h("th", { class: "r" }, "比平路"))),
      h("tbody", {}, ...r.courses.map((c) => h("tr", {},
        h("td", {}, jump(c)),
        h("td", { class: "muted" }, c.area),
        h("td", {}, tagChip(c.tag)),
        h("td", { class: "r" }, `${Math.round(c.gain_m)} m`),
        h("td", { class: "r" }, `${Math.round(c.range_m)} m`),
        h("td", { class: "r" }, pct(c.max_grade)),
        h("td", { class: "r" }, fmtDur(c.estimate_s)),
        h("td", { class: "r" }, signed(c.delta_s)))))));
}

function profileChart(c) {
  const ele = c.elevation_m;
  const lo = Math.min(...ele), hi = Math.max(...ele);
  const pad = Math.max(2, (hi - lo) * 0.15);
  const step = niceStep(hi - lo + 2 * pad, 3);
  const y0 = Math.floor((lo - pad) / step) * step;
  const y1 = Math.ceil((hi + pad) / step) * step;
  return chart({
    width: 720, height: 170, x0: 0, x1: 5, y0, y1,
    m: { t: 10, r: 12, b: 26, l: 44 },
    label: `${c.name} 高程图`,
    yTicks: ticks(y0, y1, step),
    yFmt: (v) => `${Math.round(v)} m`,
    xTicks: [0, 1, 2, 3, 4, 5].map((k) => ({ x: k, label: `${k} km` })),
    series: [{ type: "line", color: "var(--alt)", w: 2,
      data: ele.map((v, i) => ({ x: (i * c.step_m) / 1000, v })) }],
  });
}

function splitsTable(c) {
  return h("table", { class: "pr-splits" },
    h("thead", {}, h("tr", {},
      h("th", {}, "公里"), h("th", { class: "r" }, "配速"),
      h("th", { class: "r" }, "用时"), h("th", { class: "r" }, "高差"))),
    h("tbody", {}, ...c.splits.map((s) => h("tr", {},
      h("td", {}, `第 ${s.km} km`),
      h("td", { class: "r" }, `${fmtPace(s.pace_s_per_km)} /km`),
      h("td", { class: "r" }, fmtDur(s.time_s)),
      h("td", { class: "r muted" }, metres(s.net_m))))),
    h("tfoot", {}, h("tr", {},
      h("td", {}, "合计"), h("td", {}),
      h("td", { class: "r" }, fmtDur(c.estimate_s)), h("td", {}))));
}

function courseSection(c, targetS) {
  const notes = [...c.notes, c.fit_note].filter(Boolean);
  return h("section", { class: "pr-course", id: anchor(c.slug) },
    h("div", { class: "sec-head" },
      h("h2", {}, c.name, " ", tagChip(c.tag)),
      h("div", { class: "tools small" },
        h("a", { href: c.url, target: "_blank", rel: "noopener" }, "官方路线页"))),
    h("p", { class: "small" },
      c.layout, "。",
      h("span", { class: "muted" },
        ` 累计爬升 ${Math.round(c.gain_m)} m，下降 ${Math.round(c.loss_m)} m，`
        + `高差 ${Math.round(c.range_m)} m，最陡 100 m ${pct(c.max_grade)}。`)),
    profileChart(c),
    h("div", { class: "pr-body" },
      h("div", {},
        h("h3", {}, `均匀用力的分段（平路 ${fmtDur(targetS)}）`),
        splitsTable(c)),
      h("div", {},
        h("h3", {}, "跑法"),
        h("ul", { class: "pr-strategy" }, ...c.strategy.map((s) => h("li", {}, s))),
        notes.length
          ? h("div", {}, h("h3", {}, "注意"),
            h("ul", { class: "pr-notes small" }, ...notes.map((n) => h("li", {}, n))))
          : null)));
}
