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
// Charts stacked on one time axis (seconds from the first sample); pauses,
// walking and steady stretches as light bands behind every chart; a dashed
// crosshair through all of them with a one-line readout, as on the aerobic chart.

const SER_NS = "http://www.w3.org/2000/svg";
const SER_W = 960;
const SER_M = { l: 56, r: 16 };
const SER_PANEL = { h: 120, t: 10, b: 8, axis: 22 };
const SER_BANDS = [
  ["pause", "暂停", "var(--ink-3)", 0.22],
  ["walking", "走路", "var(--red)", 0.08],
  ["steady", "稳态", "var(--dot)", 0.1],
];

function serEl(tag, attrs = {}, text) {
  const el = document.createElementNS(SER_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  if (text != null) el.textContent = text;
  return el;
}

/** Robust y range: 2nd-98th percentile, so a GPS spike or a standstill does
 *  not flatten the rest of the line. Values outside are clipped to the edge. */
function serRange(values, invert) {
  const v = values.filter((x) => x != null).sort((a, b) => a - b);
  if (!v.length) return null;
  const q = (p) => v[Math.min(v.length - 1, Math.max(0, Math.round(p * (v.length - 1))))];
  let lo = q(0.02), hi = q(0.98);
  if (hi - lo < 1e-9) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.08;
  return { lo: lo - pad, hi: hi + pad, invert };
}

function serTimeLabel(t) {
  const m = Math.round(t / 60);
  return m >= 60 ? `${Math.floor(m / 60)}:${pad(m % 60)}` : `${m}′`;
}

function serTimeTicks(duration) {
  const step = [60, 120, 300, 600, 900, 1200, 1800, 3600, 7200].find((s) => duration / s <= 8) ?? 14400;
  const out = [];
  for (let t = 0; t <= duration + 1e-9; t += step) out.push(t);
  return out;
}

function seriesSection(v) {
  const s = v.series;
  if (!s) return null;
  const head = h("div", { class: "sec-head" }, h("h2", {}, "逐秒曲线"), h("div", { class: "tools" }, how(s.method)));
  const sec = h("section", { class: "run-series" }, head);
  if (!s.t_s.length) {
    sec.append(h("p", { class: "small muted" }, s.unavailable.hr_bpm ?? "没有逐秒记录"));
    return sec;
  }
  const dur = Math.max(s.duration_s, s.t_s[s.t_s.length - 1], 1);
  const sx = (t) => SER_M.l + (t / dur) * (SER_W - SER_M.l - SER_M.r);
  const panels = [
    { key: "hr_bpm", label: "心率", unit: "bpm", fmt: (x) => `${Math.round(x)}` },
    { key: "pace_s_per_km", label: "配速", unit: "/km", fmt: fmtPace, invert: true, extra: "gap_pace_s_per_km" },
    { key: "altitude_m", label: "海拔", unit: "m", fmt: (x) => `${Math.round(x)}` },
    { key: "cadence_spm", label: "步频", unit: "spm", fmt: (x) => `${Math.round(x)}` },
  ];
  const shown = panels.filter((p) => Array.isArray(s[p.key]) && s[p.key].length);
  const missing = panels.filter((p) => !shown.includes(p));
  const readout = h("div", { class: "readout", "aria-live": "polite" },
    h("span", { class: "muted" }, "鼠标移到图上，读出那一刻的数值"));
  const stack = h("div", { class: "series-stack" });
  shown.forEach((p, i) => stack.append(serPanel(s, p, sx, dur, i === shown.length - 1)));
  if (shown.length) serCrosshair(stack, readout, s, shown, sx);
  sec.append(readout, stack);
  const notes = missing.map((p) => `${p.label}：${s.unavailable[p.key] ?? "—"}`);
  if (s.gap_pace_s_per_km == null && s.pace_s_per_km != null) notes.push(`GAP 配速：${s.unavailable.gap_pace_s_per_km ?? "—"}`);
  for (const k of ["walking", "steady"]) {
    if (s.unavailable[k]) notes.push(`${k === "walking" ? "走路段" : "稳态段"}：${s.unavailable[k]}`);
  }
  if (notes.length) sec.append(h("p", { class: "small muted" }, notes.join("；")));
  sec.append(h("div", { class: "legend" },
    ...SER_BANDS.filter(([k]) => s.intervals[k]?.length).map(([, label, fill, op]) =>
      h("span", {}, h("i", { class: "bar", style: `background:${fill};opacity:${Math.min(1, op * 3)}` }), label)),
    s.gap_pace_s_per_km?.length
      ? h("span", {}, h("i", { style: "border-color:var(--ink-3);border-top-style:dashed" }), "GAP 配速（坡度折算）")
      : null,
  ));
  return sec;
}

function serPanel(s, p, sx, dur, last) {
  const H = SER_PANEL.h + (last ? SER_PANEL.axis : 0);
  const y1 = SER_PANEL.t, y2 = SER_PANEL.h - SER_PANEL.b;
  const svg = serEl("svg", { viewBox: `0 0 ${SER_W} ${H}`, preserveAspectRatio: "none", role: "img", "aria-label": `${p.label}随时间变化` });
  const wrap = h("div", { class: "chart", style: `aspect-ratio:${SER_W}/${H}` });
  wrap.append(svg);
  for (const [k, , fill, op] of SER_BANDS) {
    for (const [a, b] of s.intervals[k] ?? []) {
      svg.append(serEl("rect", { x: sx(a), y: y1, width: Math.max(1, sx(b) - sx(a)), height: y2 - y1, fill, "fill-opacity": op }));
    }
  }
  const values = p.extra && s[p.extra] ? [...s[p.key], ...s[p.extra]] : s[p.key];
  const r = serRange(values, p.invert);
  const sy = (x) => {
    const c = Math.max(r.lo, Math.min(r.hi, x));
    const f = (c - r.lo) / (r.hi - r.lo);
    return p.invert ? y1 + f * (y2 - y1) : y2 - f * (y2 - y1);
  };
  p.sy = sy;
  for (const f of [0.15, 0.5, 0.85]) {
    const val = r.lo + f * (r.hi - r.lo);
    const y = sy(val);
    svg.append(serEl("line", { x1: SER_M.l, x2: SER_W - SER_M.r, y1: y, y2: y, stroke: "var(--rule)", "stroke-width": 1 }));
    svg.append(serEl("text", { x: SER_M.l - 8, y: y + 4, "text-anchor": "end" }, p.fmt(val)));
  }
  svg.append(serEl("text", { x: SER_M.l + 4, y: y1 + 12 }, `${p.label}（${p.unit}）`));
  if (p.extra && s[p.extra]?.length) {
    svg.append(serEl("path", { d: serPath(s, s[p.extra], sx, sy), fill: "none", stroke: "var(--ink-3)", "stroke-width": 1.2, "stroke-dasharray": "3 2" }));
  }
  svg.append(serEl("path", { d: serPath(s, s[p.key], sx, sy), fill: "none", stroke: "var(--ink)", "stroke-width": 1.4, "stroke-linejoin": "round" }));
  if (last) {
    for (const t of serTimeTicks(dur)) {
      const x = sx(t);
      svg.append(serEl("line", { x1: x, x2: x, y1: y2, y2: y2 + 4, stroke: "var(--ink-3)" }));
      svg.append(serEl("text", { x, y: y2 + 17, "text-anchor": "middle" }, serTimeLabel(t)));
    }
  }
  svg.append(serEl("line", { class: "xhair", x1: 0, x2: 0, y1, y2 }));
  svg.append(serEl("circle", { class: "xhair-dot", r: 3.5, cx: 0, cy: 0 }));
  return wrap;
}

/** Lift the pen at a null value and across a pause, never interpolate. */
function serPath(s, values, sx, sy) {
  const pauses = s.intervals.pause ?? [];
  let d = "", pen = false, prevT = null;
  values.forEach((v, i) => {
    const t = s.t_s[i];
    const broken = prevT != null && pauses.some(([a, b]) => a >= prevT && b <= t);
    prevT = t;
    if (v == null) { pen = false; return; }
    d += `${pen && !broken ? "L" : "M"}${sx(t).toFixed(1)},${sy(v).toFixed(1)}`;
    pen = true;
  });
  return d;
}

function serCrosshair(stack, readout, s, shown, sx) {
  const idle = readout.innerHTML;
  const n = s.t_s.length;
  stack.addEventListener("mousemove", (e) => {
    const box = stack.querySelector("svg").getBoundingClientRect();
    const vx = ((e.clientX - box.left) / box.width) * SER_W;
    if (vx < SER_M.l - 6 || vx > SER_W - SER_M.r + 6) return hide();
    // Nearest bucket by time (t_s is sorted).
    let lo = 0, hi = n - 1;
    while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (sx(s.t_s[mid]) < vx) lo = mid; else hi = mid; }
    const i = Math.abs(sx(s.t_s[lo]) - vx) <= Math.abs(sx(s.t_s[hi]) - vx) ? lo : hi;
    const x = sx(s.t_s[i]);
    stack.querySelectorAll(".chart").forEach((wrap, k) => {
      const p = shown[k], val = s[p.key][i];
      for (const ln of wrap.querySelectorAll(".xhair")) { ln.setAttribute("x1", x); ln.setAttribute("x2", x); ln.style.opacity = 1; }
      const dot = wrap.querySelector(".xhair-dot");
      if (val != null) { dot.setAttribute("cx", x); dot.setAttribute("cy", p.sy(val)); dot.style.opacity = 1; } else dot.style.opacity = 0;
    });
    const cell = (label, arr, fmt) => (arr?.length ? h("span", {}, `${label} `, h("b", {}, arr[i] == null ? "—" : fmt(arr[i]))) : null);
    const tag = SER_BANDS.filter(([k]) => (s.intervals[k] ?? []).some(([a, b]) => a <= s.t_s[i] && s.t_s[i] <= b)).map(([, l]) => l);
    readout.replaceChildren(...[
      h("span", {}, h("b", {}, fmtDur(s.t_s[i])), tag.length ? `（${tag.join("、")}）` : ""),
      cell("心率", s.hr_bpm, (x) => `${Math.round(x)} bpm`),
      cell("配速", s.pace_s_per_km, (x) => `${fmtPace(x)} /km`),
      cell("GAP", s.gap_pace_s_per_km, (x) => `${fmtPace(x)} /km`),
      cell("海拔", s.altitude_m, (x) => `${Math.round(x)} m`),
      cell("步频", s.cadence_spm, (x) => `${Math.round(x)} spm`),
    ].filter(Boolean));
  });
  stack.addEventListener("mouseleave", hide);
  function hide() {
    for (const el of stack.querySelectorAll(".xhair, .xhair-dot")) el.style.opacity = 0;
    readout.innerHTML = idle;
  }
}


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
  seriesSection,
  // splits (ticket 04)
  splitsSection,
  // route (ticket 05)
  // metrics (ticket 06)
];
