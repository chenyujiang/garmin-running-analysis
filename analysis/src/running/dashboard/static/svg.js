// Hand-written SVG charts in the style of prototype variant A (commit 8013fab).
// Notes are HTML laid over the SVG on the right margin so they wrap.
// x is a plain number (e.g. a day index); callers map dates to numbers.

import { h } from "./dom.js";

const NS = "http://www.w3.org/2000/svg";

function s(tag, attrs = {}, text) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  if (text != null) el.textContent = text;
  return el;
}

/** A tick step giving about `n` ticks over [0, span]. */
export function niceStep(span, n = 4) {
  const raw = span / n;
  const mag = 10 ** Math.floor(Math.log10(raw || 1));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * mag >= raw) return m * mag;
  return 10 * mag;
}

export function ticks(lo, hi, step) {
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(v);
  return out;
}

/**
 * o: { width, height, x0, x1, y0, y1, yTicks, yFmt, zero, label, m: {t,r,b,l},
 *      xTicks: [{x, label}],
 *      series: [{ type: "line"|"area0", data: [{x, v}], color, w, pos, neg }],
 *      notes: [{ x, v, node }] }   // at most 2 notes per chart
 * Returns a <div class="chart">.
 */
export function chart(o) {
  const W = o.width, H = o.height;
  const m = { t: 14, r: 16, b: 26, l: 40, ...(o.m || {}) };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const sx = (x) => m.l + ((x - o.x0) / (o.x1 - o.x0 || 1)) * iw;
  const sy = (v) => m.t + ih - ((v - o.y0) / (o.y1 - o.y0 || 1)) * ih;
  const yFmt = o.yFmt || ((v) => String(Math.round(v)));

  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img", "aria-label": o.label || "" });
  for (const v of o.yTicks || []) {
    const y = sy(v);
    svg.append(s("line", { x1: m.l, x2: W - m.r, y1: y, y2: y, stroke: v === 0 && o.zero ? "var(--ink-3)" : "var(--rule)", "stroke-width": 1 }));
    svg.append(s("text", { x: m.l - 8, y: y + 4, "text-anchor": "end" }, yFmt(v)));
  }
  for (const t of o.xTicks || []) {
    const x = sx(t.x);
    svg.append(s("line", { x1: x, x2: x, y1: H - m.b, y2: H - m.b + 4, stroke: "var(--ink-3)" }));
    svg.append(s("text", { x, y: H - m.b + 17, "text-anchor": "middle" }, t.label));
  }
  for (const sr of o.series) {
    const pts = sr.data.filter((p) => p.v != null);
    if (!pts.length) continue;
    if (sr.type === "area0") {
      for (const sign of [1, -1]) {
        let d = `M${sx(pts[0].x)},${sy(0)}`;
        for (const p of pts) d += `L${sx(p.x)},${sy(sign > 0 ? Math.max(0, p.v) : Math.min(0, p.v))}`;
        d += `L${sx(pts[pts.length - 1].x)},${sy(0)}Z`;
        svg.append(s("path", { d, fill: sign > 0 ? sr.pos : sr.neg, opacity: 0.85 }));
      }
    } else {
      const d = pts.map((p, i) => `${i ? "L" : "M"}${sx(p.x).toFixed(1)},${sy(p.v).toFixed(1)}`).join("");
      svg.append(s("path", { d, fill: "none", stroke: sr.color, "stroke-width": sr.w || 2, "stroke-linejoin": "round" }));
    }
  }

  const wrap = h("div", { class: "chart", style: `aspect-ratio:${W}/${H}` });
  wrap.append(svg);
  const placed = [];
  for (const n of (o.notes || []).slice(0, 2)) {
    const px = sx(n.x), py = sy(n.v);
    let ty = Math.max(m.t, py - 10);
    for (const q of placed) if (Math.abs(ty - q) < 52) ty = q + 52;
    placed.push(ty);
    svg.append(s("circle", { cx: px, cy: py, r: 4.5, fill: "none", stroke: "var(--red)", "stroke-width": 1.5 }));
    svg.append(s("polyline", { points: `${px + 5},${py} ${W - m.r + 6},${ty + 8} ${W - m.r + 12},${ty + 8}`, fill: "none", stroke: "var(--red)", "stroke-width": 1 }));
    const note = h("div", { class: "note", style: `left:${((W - m.r + 16) / W) * 100}%;top:${(ty / H) * 100}%;width:${((m.r - 18) / W) * 100}%` });
    note.append(n.node);
    wrap.append(note);
  }
  return wrap;
}
