// Load column of the status band (ticket 09): headline, CTL/ATL/TSB,
// 12-week CTL/ATL lines with TSB area, and "负荷怎么算的".
// Data: GET /api/load (see running.load.training_load).

import { h } from "./dom.js";
import { chart, niceStep, ticks } from "./svg.js";

const f0 = (x) => String(Math.round(x));
const signed = (x) => (Math.round(x) > 0 ? "+" : Math.round(x) < 0 ? "−" : "") + Math.abs(Math.round(x));
const md = (iso) => `${Number(iso.slice(5, 7))} 月 ${Number(iso.slice(8, 10))} 日`;
const mdShort = (iso) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`;

function tsbWord(tsb) {
  if (tsb < -25) return ["疲劳累积", "TSB 低于 −25，这几天安排轻松跑或休息。"];
  if (tsb < -10) return ["正在训练", "TSB 在常见的训练区间，可以按计划继续。"];
  if (tsb < 5) return ["平衡", "体能和疲劳大致持平。"];
  return ["恢复充分", "疲劳已经消退，适合安排质量课或比赛。"];
}

/** The section element (band column 1); it fills itself once the data arrives.
 *  `?today=YYYY-MM-DD` on the page URL shows the load as of that day. */
export function loadSection() {
  const sec = h("section", { class: "band-load" }, h("h2", {}, "训练负荷"),
    h("p", { class: "small muted" }, "正在读取…"));
  fill(sec);
  return sec;
}

async function fill(sec) {
  const today = new URLSearchParams(location.search).get("today");
  const q = today ? `?today=${encodeURIComponent(today)}` : "";
  let L;
  try {
    const r = await fetch(`api/load${q}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    L = await r.json();
  } catch (err) {
    sec.replaceChildren(h("h2", {}, "训练负荷"), h("p", { class: "warn" }, `无法读取训练负荷：${err.message}`));
    return;
  }
  sec.replaceChildren(...render(L).filter(Boolean));
}

function render(L) {
  if (!L.has_data) {
    return [
      h("h2", {}, "训练负荷"),
      h("p", { class: "small muted" }, "还没有可计算的活动。"),
      L.config_error ? h("p", { class: "warn small" }, L.config_error) : null,
      howDetails(L.method),
    ];
  }
  const c = L.current;
  const [word, advice] = tsbWord(c.tsb);
  const headline = L.spike
    ? h("h1", { class: "headline alert" }, `负荷突增：ATL 是 CTL 的 ${c.ratio.toFixed(1)} 倍`)
    : h("h1", { class: "headline" }, `训练负荷${word}`);
  const dek = L.spike
    ? h("p", { class: "dek" }, `从 ${md(L.spike_since)}起 ATL/CTL 超过 1.5。接下来几天降一点量，让 ATL 回到 CTL 的 1.5 倍以内。`)
    : h("p", { class: "dek" }, advice);

  return [
    headline,
    dek,
    h("div", { class: "stat-line" },
      big("CTL 体能", f0(c.ctl), "var(--fit)"),
      big("ATL 疲劳", f0(c.atl), "var(--fat)"),
      big("TSB 状态", signed(c.tsb), c.tsb < 0 ? "var(--red)" : "var(--form-pos)"),
    ),
    ...charts(L),
    h("div", { class: "load-foot" },
      h("div", { class: "legend" },
        legend("CTL 42 天", "border-color:var(--fit)"),
        legend("ATL 7 天", "border-color:var(--fat)"),
        legend("TSB", "background:var(--form-neg)", "bar"),
      ),
      howDetails(L.method),
    ),
    missingNote(L),
  ];
}

function charts(L) {
  const pts = L.series.map((p, i) => ({ ...p, x: i }));
  const x1 = Math.max(1, pts.length - 1);
  // A date label every two weeks, counted back from the last day.
  const xTicks = pts.filter((p) => (pts.length - 1 - p.x) % 14 === 0)
    .map((p) => ({ x: p.x, label: mdShort(p.date) }));

  const top = Math.max(10, ...pts.map((p) => Math.max(p.ctl, p.atl)));
  const step = niceStep(top);
  const y1 = Math.ceil(top / step) * step;
  const notes = [];
  if (L.spike && L.spike_since) {
    const p = pts.find((q) => q.date === L.spike_since);
    if (p) notes.push({ x: p.x, v: p.atl, node: h("span", {}, h("b", {}, `${md(p.date)}起`), "ATL/CTL 超过 1.5。") });
  }
  const loadChart = chart({
    width: 560, height: 190, x0: 0, x1, y0: 0, y1, yTicks: ticks(0, y1, step),
    m: { r: notes.length ? 150 : 16, l: 34 }, label: "近 12 周 CTL 与 ATL", xTicks,
    series: [
      { data: pts.map((p) => ({ x: p.x, v: p.ctl })), color: "var(--fit)", w: 2.2 },
      { data: pts.map((p) => ({ x: p.x, v: p.atl })), color: "var(--fat)", w: 1.6 },
    ],
    notes,
  });

  const lo = Math.min(-10, ...pts.map((p) => p.tsb)), hi = Math.max(10, ...pts.map((p) => p.tsb));
  const tStep = niceStep(hi - lo, 3);
  const tsbChart = chart({
    width: 560, height: 78, x0: 0, x1,
    y0: Math.floor(lo / tStep) * tStep, y1: Math.ceil(hi / tStep) * tStep,
    yTicks: [Math.floor(lo / tStep) * tStep, 0], zero: true,
    yFmt: (v) => (v === 0 ? "0" : signed(v)),
    m: { r: notes.length ? 150 : 16, l: 34, t: 6, b: 6 }, label: "近 12 周 TSB",
    series: [{ type: "area0", data: pts.map((p) => ({ x: p.x, v: p.tsb })), pos: "var(--form-pos)", neg: "var(--form-neg)" }],
  });
  return [loadChart, tsbChart];
}

function big(label, value, color) {
  return h("div", {}, h("span", { class: "l" }, label), h("span", { class: "big", style: `color:${color}` }, value));
}

function legend(label, style, cls = "") {
  return h("span", {}, h("i", { class: cls, style }), label);
}

function missingNote(L) {
  const n = L.missing_hr_recent.length;
  if (!n) return null;
  return h("p", { class: "small muted" }, `近 12 周有 ${n} 个活动没有心率，记为缺失，没有计入负荷。`);
}

function howDetails(m) {
  const params = m.hr_max == null
    ? "config.toml 里没有当前生效的生理参数。"
    : `当前参数：HRrest ${m.hr_rest}、HRmax ${m.hr_max}（${m.physiology_effective_from} 起生效）。`;
  return h("details", { class: "how" },
    h("summary", {}, "负荷怎么算的"),
    h("div", { class: "body" },
      h("p", {}, `${m.trimp}：${m.trimp_formula}。`, params,
        "每个活动用它当天生效的那组参数。所有带心率的活动都计入，没有心率的活动记为缺失，不估算。",
        `相邻两个心率样本的间隔超过 ${m.max_sample_gap_s} 秒时（暂停）只按 ${m.max_sample_gap_s} 秒算。`),
      h("p", {}, `CTL 是 ${m.ctl_days} 天、ATL 是 ${m.atl_days} 天的指数加权平均，递推用 ${m.recursion} 形式：${m.recursion_formula}。`,
        `${m.tsb_formula}。ATL/CTL 超过 ${m.spike_ratio} 时提示负荷突增。数值只作相对比较。`),
    ),
  );
}
