// Activity detail page, #/run/<id> (run-detail tickets 02-07).
// Reads GET /api/activities/<id> once; every section renders from that body.
//
// Each section is one renderer `(detail) => Node | null` in RENDERERS, in page
// order, with its code in its own block below. Later tickets add one line in
// their slot of RENDERERS and their functions in their block.

import { h, fmtDate } from "./dom.js";
import { typeName } from "./runs.js";
import { niceStep } from "./svg.js"; // route scale bar (ticket 05)

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


// --- route shape (ticket 05) -------------------------------------------------
// The API gives only a normalised shape (x, y in [0, 1], y grows southwards)
// and metres per unit; no coordinates and no map tiles, so nothing here can
// place the run on a map.

const ROUTE_PX = 420; // pixels per unit along the longer side
const ROUTE_PAD = 18;

function svgEl(tag, attrs = {}, text) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  if (text != null) el.textContent = text;
  return el;
}

function fmtMetres(m) {
  return m >= 1000 ? `${m / 1000} km` : `${m} m`;
}

function routeSection(v) {
  const head = (tools) => h("div", { class: "sec-head" }, h("h2", {}, "路线形状"), tools);
  const r = v.route;
  if (!r) {
    return h("section", { class: "run-route" },
      head(h("div", { class: "tools" })),
      h("p", { class: "small muted" }, v.route_unavailable || "没有路线"),
    );
  }
  const w = Math.max(...r.x), hh = Math.max(...r.y);
  const px = (x) => ROUTE_PAD + x * ROUTE_PX;
  const py = (y) => ROUTE_PAD + y * ROUTE_PX;
  // Scale bar: a round length near a quarter of the longer side.
  const barM = niceStep(Math.max(w, hh) * r.metres_per_unit, 4);
  const barPx = (barM / r.metres_per_unit) * ROUTE_PX;
  const W = Math.max(w * ROUTE_PX, barPx + 60) + 2 * ROUTE_PAD; // room for the bar on a thin route
  const barY = hh * ROUTE_PX + 2 * ROUTE_PAD + 6;
  const H = barY + 24;

  const svg = svgEl("svg", {
    viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img",
    "aria-label": "路线形状（不含地图）",
  });
  const points = r.x.map((x, i) => `${px(x).toFixed(1)},${py(r.y[i]).toFixed(1)}`).join(" ");
  svg.append(svgEl("polyline", { points, class: "route-line" }));

  const [sx, sy] = [px(r.x[r.start_index]), py(r.y[r.start_index])];
  const [fx, fy] = [px(r.x[r.finish_index]), py(r.y[r.finish_index])];
  svg.append(svgEl("circle", { cx: fx, cy: fy, r: 5, class: "route-finish" }));
  svg.append(svgEl("circle", { cx: sx, cy: sy, r: 7, class: "route-start" }));

  const x0 = ROUTE_PAD;
  svg.append(svgEl("path", { d: `M${x0},${barY - 4}V${barY}H${x0 + barPx}V${barY - 4}`, class: "route-scale" }));
  svg.append(svgEl("text", { x: x0 + barPx + 6, y: barY + 4 }, fmtMetres(barM)));

  return h("section", { class: "run-route" },
    head(h("div", { class: "tools" }, how(r.method))),
    h("div", { class: "route-box" }, svg),
    h("p", { class: "small muted" }, "空心圆为起点，实心圆为终点；上方为北。只画形状，不加载地图。"),
  );
}


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
  // route (ticket 05)
  routeSection,
  // metrics (ticket 06)
];
