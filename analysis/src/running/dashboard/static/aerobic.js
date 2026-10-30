// Aerobic trend, the full-width second screen (ticket 12). Reads GET /api/aerobic.
// Prototype variant A layout (commit 8013fab): pace at the reference heart rate,
// faster is higher; dots = weekly median, line = 4-week rolling median, a weekly
// temperature strip below on the same x axis. Crosshair readout as in variant C.
// Empty weeks stay empty: no dot, and both the line and the bars break there.

import { h } from "./dom.js";

const NS = "http://www.w3.org/2000/svg";
const RANGES = [["6m", "半年"], ["1y", "1 年"], ["2y", "2 年"], ["all", "全部"]];
const SINCE = { "6m": "半年前", "1y": "一年前", "2y": "两年前", all: "最早" };

// Shared geometry: both charts use the same width and left/right margins so
// their plot areas line up; the right margin holds the editorial notes.
const W = 1256;
const M = { l: 50, r: 230 };
const MAIN = { h: 330, t: 14, b: 26 };
const TEMP = { h: 74, t: 6, b: 24 };

function s(tag, attrs = {}, text) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  if (text != null) el.textContent = text;
  return el;
}

export const fmtPace = (sec) => {
  if (sec == null) return "—";
  const r = Math.round(sec);
  return `${Math.floor(r / 60)}:${String(r % 60).padStart(2, "0")}`;
};
const md = (iso) => `${Number(iso.slice(5, 7))} 月 ${Number(iso.slice(8, 10))} 日`;
const addDays = (iso, n) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

/** The section element; it fills itself and refetches on range change.
 *  `?today=YYYY-MM-DD` on the page URL pins the date, as for the other blocks. */
export function aerobicSection() {
  const state = { range: "1y" };
  const sec = h("section", { class: "aerobic" });
  const body = h("div", { class: "aerobic-body" }, h("p", { class: "small muted" }, "正在读取…"));
  const seg = h("div", { class: "seg", role: "group", "aria-label": "时间范围" },
    ...RANGES.map(([key, label]) => h("button", { type: "button", "data-range": key, "aria-pressed": String(key === state.range) }, label)));
  const howSlot = h("span", {});
  const title = h("h2", {}, "有氧能力：参考心率下的跑步配速");
  seg.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-range]");
    if (!b || b.dataset.range === state.range) return;
    state.range = b.dataset.range;
    for (const x of seg.querySelectorAll("button")) x.setAttribute("aria-pressed", String(x === b));
    fill(body, howSlot, title, state.range);
  });
  sec.append(
    h("div", { class: "sec-head" },
      title,
      h("span", { class: "muted small" }, "越高越快"),
      h("div", { class: "tools" }, seg, howSlot),
    ),
    body,
  );
  fill(body, howSlot, title, state.range);
  return sec;
}

let seq = 0;
async function fill(body, howSlot, title, range) {
  const mine = ++seq;
  const today = new URLSearchParams(location.search).get("today");
  const q = new URLSearchParams({ range });
  if (today) q.set("today", today);
  let A;
  try {
    const r = await fetch(`api/aerobic?${q}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    A = await r.json();
  } catch (err) {
    if (mine !== seq) return;
    body.replaceChildren(h("p", { class: "warn" }, `无法读取有氧能力：${err.message}`));
    return;
  }
  if (mine !== seq) return; // a newer range was picked while this one loaded
  howSlot.replaceChildren(howDetails(A.method));
  title.textContent = `有氧能力：心率 ${A.method.params.reference_hr} 时的跑步配速`;
  body.replaceChildren(...render(A));
}

function render(A) {
  const ref = A.method.params.reference_hr;
  const weeks = A.weeks.map((w, i) => ({ ...w, x: i }));
  const hasPoints = weeks.some((w) => w.pace_s_per_km != null);
  if (!A.has_data || !hasPoints) {
    return [h("p", { class: "dek" }, A.has_data
      ? "这个时间范围里没有一周有 2 次以上的有效路跑，换一个更长的范围看看。"
      : `还没有可用的户外路跑：需要心率在 ${ref} bpm 附近、稳态时长至少 ${A.method.params.min_steady_s / 60} 分钟的跑步。`)];
  }
  const g = geometry(weeks);
  const main = mainChart(weeks, g, ref);
  const temp = tempChart(weeks, g);
  const readout = h("div", { class: "readout", "aria-live": "polite" },
    h("span", { class: "muted" }, "鼠标移到图上，读出那一周的数值"));
  const stack = h("div", { class: "aerobic-stack" },
    main,
    h("div", { class: "small muted temp-label" }, "每周平均温度（手表记录，未校正）"),
    temp,
  );
  wireCrosshair(stack, readout, weeks, g, ref);
  return [
    h("div", { class: "aerobic-top" }, dek(weeks, A.range), readout),
    stack,
    h("div", { class: "legend" },
      h("span", {}, h("i", { class: "dotk" }), "每周中位数（空白 = 有效跑步少于 2 次）"),
      h("span", {}, h("i", { style: "border-color:var(--ink)" }), "4 周滚动中位数"),
      h("span", {}, h("i", { class: "dotk open" }), "本周（未完）"),
    ),
  ];
}

function dek(weeks, range) {
  const rolled = weeks.filter((w) => w.rolling_pace_s_per_km != null);
  const last = rolled[rolled.length - 1], first = rolled[0];
  const parts = [`最近 4 周 `, h("span", { class: "num" }, `${fmtPace(last.rolling_pace_s_per_km)} /km`)];
  if (first !== last) {
    const diff = last.rolling_pace_s_per_km - first.rolling_pace_s_per_km;
    const label = range === "all" ? `最早（${first.week_start.slice(0, 7)}）` : SINCE[range];
    parts.push(`，${label} `, h("span", { class: "num" }, `${fmtPace(first.rolling_pace_s_per_km)} /km`),
      Math.round(diff) === 0 ? "，持平。" : diff < 0 ? `，快了 ${Math.round(-diff)} 秒。` : `，慢了 ${Math.round(diff)} 秒。`);
  } else {
    parts.push("。");
  }
  return h("p", { class: "dek" }, ...parts);
}

// x: week index; y: pace in s/km with the axis inverted (faster = higher).
function geometry(weeks) {
  const n = weeks.length;
  const iw = W - M.l - M.r;
  const paces = weeks.flatMap((w) => [w.pace_s_per_km, w.rolling_pace_s_per_km]).filter((v) => v != null);
  const span = Math.max(...paces) - Math.min(...paces);
  const step = span <= 40 ? 10 : span <= 80 ? 20 : span <= 120 ? 30 : 60;
  const slow = Math.ceil(Math.max(...paces) / step) * step;
  const fast = Math.floor(Math.min(...paces) / step) * step;
  const sx = (x) => M.l + (n > 1 ? x / (n - 1) : 0.5) * iw;
  const sy = (v) => MAIN.t + ((v - fast) / (slow - fast || 1)) * (MAIN.h - MAIN.t - MAIN.b);
  const yTicks = [];
  for (let v = fast; v <= slow + 1e-9; v += step) yTicks.push(v);
  return { n, iw, sx, sy, yTicks, xTicks: monthTicks(weeks) };
}

/** Month boundaries: every month up to ~1 year, every 3 months up to ~2.5
 *  years, otherwise every January. January is labelled with the year. */
function monthTicks(weeks) {
  const n = weeks.length;
  const every = n <= 60 ? 1 : n <= 130 ? 3 : 12;
  const out = [];
  let prev = null;
  for (const w of weeks) {
    // The tick goes on the first Monday of the month.
    const month = w.week_start.slice(0, 7);
    if (prev != null && month !== prev) {
      const mo = Number(month.slice(5, 7));
      if ((mo - 1) % every === 0) out.push({ x: w.x, label: mo === 1 ? month.slice(0, 4) : `${mo}月` });
    }
    prev = month;
  }
  return out;
}

function axisX(svg, g, H, b) {
  for (const t of g.xTicks) {
    const x = g.sx(t.x);
    svg.append(s("line", { x1: x, x2: x, y1: H - b, y2: H - b + 4, stroke: "var(--ink-3)" }));
    svg.append(s("text", { x, y: H - b + 17, "text-anchor": "middle" }, t.label));
  }
}

function frame(H, label) {
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img", "aria-label": label });
  const wrap = h("div", { class: "chart", style: `aspect-ratio:${W}/${H}` });
  wrap.append(svg);
  return [wrap, svg];
}

function mainChart(weeks, g, ref) {
  const H = MAIN.h;
  const [wrap, svg] = frame(H, `有氧能力趋势：心率 ${ref} 时的配速`);
  for (const v of g.yTicks) {
    const y = g.sy(v);
    svg.append(s("line", { x1: M.l, x2: W - M.r, y1: y, y2: y, stroke: "var(--rule)", "stroke-width": 1 }));
    svg.append(s("text", { x: M.l - 8, y: y + 4, "text-anchor": "end" }, fmtPace(v)));
  }
  axisX(svg, g, H, MAIN.b);

  for (const w of weeks) {
    if (w.pace_s_per_km == null) continue;
    svg.append(w.complete
      ? s("circle", { cx: g.sx(w.x), cy: g.sy(w.pace_s_per_km), r: 2.6, fill: "var(--dot)" })
      : s("circle", { cx: g.sx(w.x), cy: g.sy(w.pace_s_per_km), r: 3, fill: "var(--paper)", stroke: "var(--dot)", "stroke-width": 1.4 }));
  }
  // Rolling line: lift the pen at every empty week, never interpolate.
  // A lone rolling point between two gaps is drawn as a short level dash.
  let d = "";
  weeks.forEach((w, i) => {
    const v = w.rolling_pace_s_per_km;
    if (v == null) return;
    const x = g.sx(w.x).toFixed(1), y = g.sy(v).toFixed(1);
    const prev = weeks[i - 1]?.rolling_pace_s_per_km, next = weeks[i + 1]?.rolling_pace_s_per_km;
    if (prev != null) d += `L${x},${y}`;
    else if (next != null) d += `M${x},${y}`;
    else d += `M${(+x - 4).toFixed(1)},${y}L${(+x + 4).toFixed(1)},${y}`;
  });
  svg.append(s("path", { d, fill: "none", stroke: "var(--ink)", "stroke-width": 2.4, "stroke-linejoin": "round", "stroke-linecap": "round" }));

  const xhair = s("line", { class: "xhair", x1: 0, x2: 0, y1: MAIN.t, y2: H - MAIN.b });
  const mark = s("circle", { class: "xhair-dot", r: 4, cx: 0, cy: 0 });
  svg.append(xhair, mark);
  notes(wrap, svg, weeks, g);
  return wrap;
}

/** At most two editorial notes: the fastest 4-week stretch in range, and the
 *  hottest week (temperature is not corrected, so warm weeks read slower). */
function notes(wrap, svg, weeks, g) {
  const rolled = weeks.filter((w) => w.rolling_pace_s_per_km != null);
  const out = [];
  const best = rolled.reduce((a, b) => (b.rolling_pace_s_per_km < a.rolling_pace_s_per_km ? b : a));
  if (rolled.length >= 4) {
    out.push({ w: best, v: best.rolling_pace_s_per_km,
      node: h("span", {}, h("b", {}, `最快：${fmtPace(best.rolling_pace_s_per_km)} /km`), `${md(best.week_start)}那周的 4 周滚动中位数。`) });
  }
  const warm = weeks.filter((w) => w.pace_s_per_km != null && w.temperature_c != null);
  if (warm.length >= 4) {
    const hot = warm.reduce((a, b) => (b.temperature_c > a.temperature_c ? b : a));
    const temps = warm.map((w) => w.temperature_c).sort((a, b) => a - b);
    const median = temps[Math.floor(temps.length / 2)];
    if (hot !== best && hot.temperature_c - median >= 5) {
      out.push({ w: hot, v: hot.pace_s_per_km,
        node: h("span", {}, h("b", {}, `最热：周均 ${Math.round(hot.temperature_c)}°C`), `${md(hot.week_start)}那周，配速 ${fmtPace(hot.pace_s_per_km)} /km。温度未校正，热天会显得慢。`) });
    }
  }
  const placed = [];
  for (const n of out.slice(0, 2)) {
    const px = g.sx(n.w.x), py = g.sy(n.v);
    let ty = Math.max(MAIN.t, py - 10);
    for (const q of placed) if (Math.abs(ty - q) < 62) ty = q + 62;
    ty = Math.min(ty, MAIN.h - MAIN.b - 50);
    placed.push(ty);
    svg.append(s("circle", { cx: px, cy: py, r: 4.5, fill: "none", stroke: "var(--red)", "stroke-width": 1.5 }));
    svg.append(s("polyline", { points: `${px + 5},${py} ${W - M.r + 6},${ty + 8} ${W - M.r + 12},${ty + 8}`, fill: "none", stroke: "var(--red)", "stroke-width": 1 }));
    const note = h("div", { class: "note", style: `left:${((W - M.r + 16) / W) * 100}%;top:${(ty / MAIN.h) * 100}%;width:${((M.r - 18) / W) * 100}%` });
    note.append(n.node);
    wrap.append(note);
  }
}

function tempChart(weeks, g) {
  const H = TEMP.h;
  const [wrap, svg] = frame(H, "每周平均温度");
  const temps = weeks.map((w) => w.temperature_c).filter((v) => v != null);
  const lo = Math.min(0, Math.floor(Math.min(...temps, 0) / 5) * 5);
  const hi = Math.max(25, Math.ceil(Math.max(...temps, 0) / 5) * 5);
  const ih = H - TEMP.t - TEMP.b;
  const sy = (v) => TEMP.t + ih - ((v - lo) / (hi - lo)) * ih;
  for (const v of lo < 0 ? [lo, 0, hi] : [0, hi]) {
    svg.append(s("line", { x1: M.l, x2: W - M.r, y1: sy(v), y2: sy(v), stroke: v === 0 ? "var(--ink-3)" : "var(--rule)", "stroke-width": 1 }));
    svg.append(s("text", { x: M.l - 8, y: sy(v) + 4, "text-anchor": "end" }, `${v}°`));
  }
  axisX(svg, g, H, TEMP.b);
  const bw = Math.max(1, Math.min(10, (g.iw / Math.max(1, g.n - 1)) * 0.7));
  for (const w of weeks) {
    if (w.temperature_c == null) continue;
    const y = sy(w.temperature_c), y0 = sy(0);
    svg.append(s("rect", { x: g.sx(w.x) - bw / 2, y: Math.min(y, y0), width: bw, height: Math.max(0.5, Math.abs(y0 - y)), fill: "var(--temp)" }));
  }
  svg.append(s("line", { class: "xhair", x1: 0, x2: 0, y1: TEMP.t, y2: H - TEMP.b }));
  return wrap;
}

/** Variant C: a dashed vertical line through both charts, snapped to the
 *  nearest week, and a one-line readout of that week's numbers. */
function wireCrosshair(stack, readout, weeks, g, ref) {
  const idle = readout.innerHTML;
  const lines = () => stack.querySelectorAll(".xhair");
  const dot = () => stack.querySelector(".xhair-dot");
  stack.addEventListener("mousemove", (e) => {
    const box = stack.querySelector("svg").getBoundingClientRect();
    const vx = ((e.clientX - box.left) / box.width) * W;
    if (vx < M.l - 6 || vx > W - M.r + 6) return hide();
    const i = Math.round(((vx - M.l) / g.iw) * (g.n - 1));
    const w = weeks[Math.max(0, Math.min(g.n - 1, i))];
    const x = g.sx(w.x);
    for (const ln of lines()) { ln.setAttribute("x1", x); ln.setAttribute("x2", x); ln.style.opacity = 1; }
    const p = w.rolling_pace_s_per_km ?? w.pace_s_per_km;
    const d = dot();
    if (p != null) { d.setAttribute("cx", x); d.setAttribute("cy", g.sy(p)); d.style.opacity = 1; } else d.style.opacity = 0;
    readout.replaceChildren(
      h("span", {}, h("b", {}, `${w.week_start.replaceAll("-", ".")}–${addDays(w.week_start, 6).slice(5).replace("-", ".")}`), w.complete ? "" : "（本周未完）"),
      h("span", {}, "周中位数 ", h("b", {}, w.pace_s_per_km == null ? "—" : `${fmtPace(w.pace_s_per_km)} /km`)),
      h("span", {}, "4 周滚动 ", h("b", {}, w.rolling_pace_s_per_km == null ? "—" : `${fmtPace(w.rolling_pace_s_per_km)} /km`)),
      h("span", {}, "有效跑步 ", h("b", {}, String(w.runs)), " 次"),
      h("span", {}, "温度 ", h("b", {}, w.temperature_c == null ? "—" : `${Math.round(w.temperature_c)}°C`)),
    );
    readout.title = `心率 ${ref} bpm 时的配速`;
  });
  stack.addEventListener("mouseleave", hide);
  function hide() {
    for (const ln of lines()) ln.style.opacity = 0;
    dot().style.opacity = 0;
    readout.innerHTML = idle;
  }
}

function howDetails(m) {
  return h("details", { class: "how" },
    h("summary", {}, "有氧能力怎么算的"),
    h("div", { class: "body" }, h("p", {}, `${m.name}。`, m.description)),
  );
}
