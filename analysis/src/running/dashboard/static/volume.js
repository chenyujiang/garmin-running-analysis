// Weekly volume column of the top band (ticket 10). Reads GET /api/volume.
// Prototype variant A: three numbers, a 12-week bar chart (this week in grey),
// and a "how is this calculated" note.

import { watch } from "./changes.js";
import { h } from "./dom.js";

const SVG_NS = "http://www.w3.org/2000/svg";

/** The section element; it fills itself once the data arrives.
 *  `?today=YYYY-MM-DD` on the page URL shows the volume as of that day. */
export function volumeSection() {
  const section = h("section", { class: "band-volume" }, h("h2", {}, "周跑量"),
    h("p", { class: "small muted" }, "正在读取…"));
  load(section);
  return section;
}

async function load(section) {
  const today = new URLSearchParams(location.search).get("today");
  const q = today ? `?today=${encodeURIComponent(today)}` : "";
  let v;
  try {
    const r = await fetch(`api/volume${q}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    v = await r.json();
  } catch (err) {
    section.replaceChildren(h("h2", {}, "周跑量"), h("p", { class: "warn" }, `无法读取周跑量：${err.message}`));
    return;
  }
  section.replaceChildren(...render(v));
}

const km = (m) => (m / 1000).toFixed(1);

function render(v) {
  return [
    h("h2", {}, "周跑量"),
    h("div", { class: "stat-line" },
      stat("本周（周一至今）", v.this_week.distance_m, "volume.this_week"),
      stat("上周", v.last_week.distance_m, "volume.last_week"),
      stat("滚动 7 天", v.rolling_7d.distance_m, "volume.rolling_7d"),
    ),
    barChart(v.weeks),
    h("div", { class: "foot" },
      h("span", { class: "small muted" }, "只算跑的距离，走路不计。本周未完。"),
      how(v.method),
    ),
    v.garmin_totals_runs
      ? h("p", { class: "small muted" },
        `近 12 周有 ${v.garmin_totals_runs} 次跑步没有步频，用的是 Garmin 的总距离和总时长（走路也算在内）。`)
      : null,
  ].filter(Boolean);
}

function stat(label, meters, key) {
  return h("div", {}, h("span", { class: "l" }, label),
    watch(h("span", { class: "big" }, km(meters), h("span", { class: "small muted" }, " km")), key, km(meters)));
}

function how(method) {
  const p = method.params;
  return h("details", { class: "how" },
    h("summary", {}, "跑量怎么算的"),
    h("div", { class: "body" },
      h("p", {}, method.description),
      h("p", { class: "muted" },
        `当前参数：跑的步频阈值 ${p.cadence_spm} spm，平滑 ${p.smoothing_s} 秒，`
        + `走路少于 ${p.min_walk_s} 秒仍算跑，采样间隔超过 ${p.pause_gap_s} 秒算暂停。`
        + `计入的活动类型：${p.activity_types.join("、")}。`),
    ),
  );
}

function svg(tag, attrs = {}, text) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, val] of Object.entries(attrs)) el.setAttribute(k, val);
  if (text != null) el.textContent = text;
  return el;
}

/** Hand-written SVG bars, one per week, oldest left. Unfinished week in grey. */
function barChart(weeks) {
  const W = 380, H = 190, m = { t: 14, r: 8, b: 26, l: 30 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const maxKm = Math.max(10, ...weeks.map((w) => w.distance_m / 1000));
  const step = maxKm > 60 ? 20 : maxKm > 30 ? 10 : 5;
  const top = Math.ceil(maxKm / step) * step;
  const sy = (k) => m.t + ih - (k / top) * ih;
  const slot = iw / weeks.length, bw = slot * 0.72;

  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img",
    "aria-label": "近 12 周周跑量" });
  for (let k = 0; k <= top; k += step) {
    const y = sy(k);
    root.append(svg("line", { x1: m.l, x2: W - m.r, y1: y, y2: y, stroke: "var(--rule)", "stroke-width": 1 }));
    root.append(svg("text", { x: m.l - 8, y: y + 4, "text-anchor": "end" }, String(k)));
  }
  weeks.forEach((w, i) => {
    const x = m.l + i * slot + (slot - bw) / 2;
    const k = w.distance_m / 1000;
    if (k > 0) {
      const bar = svg("rect", { x, y: sy(k), width: bw, height: sy(0) - sy(k),
        fill: w.complete ? "var(--ink)" : "var(--ink-3)" });
      bar.append(svg("title", {}, `${w.week_start} 起一周：${km(w.distance_m)} km，${w.runs} 次跑步${w.complete ? "" : "（未完）"}`));
      root.append(bar);
    }
    if ((weeks.length - 1 - i) % 3 === 0) {  // every third week, ending at this week
      const [, mo, d] = w.week_start.split("-");
      root.append(svg("text", { x: x + bw / 2, y: H - m.b + 17, "text-anchor": "middle" },
        `${Number(mo)}/${Number(d)}`));
    }
  });
  return h("div", { class: "chart", style: `aspect-ratio:${W}/${H}` }, root);
}
