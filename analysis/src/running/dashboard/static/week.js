// "本周" strip at the top of the home page. Reads GET /api/plan-review (the
// sessions the last `running-push-plan --apply` put on the Garmin calendar)
// and answers "what is on this week": plan week n of 8, each session of the
// week with its status, and the next session still to run. Without a push it
// points at the plan page instead.

import { h } from "./dom.js";
import { dayLabel } from "./review.js";

const KIND = { quality: "质量课", race: "比赛", easy: "E 跑", long: "长距离" };
const STATUS = { done: "已跑", missed: "未跑", today: "今天", upcoming: "待跑" };
const DAY_MS = 86400000;

export function weekSection() {
  const root = h("section", { class: "week-strip", "aria-label": "本周" },
    h("p", { class: "loading small" }, "正在读取本周计划…"));
  load(root);
  return root;
}

async function load(root) {
  const params = new URLSearchParams();
  const today = new URLSearchParams(location.search).get("today");
  if (today) params.set("today", today);
  let r;
  try {
    const res = await fetch(`api/plan-review?${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    r = await res.json();
  } catch (err) {
    root.replaceChildren(h("p", { class: "warn" }, `无法读取本周计划：${err.message}`));
    return;
  }
  root.replaceChildren(...render(r));
}

/** Days from `a` to `b`, both "YYYY-MM-DD". */
const daysBetween = (a, b) => Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / DAY_MS);
export const addDays = (iso, n) => new Date(Date.parse(`${iso}T00:00:00Z`) + n * DAY_MS).toISOString().slice(0, 10);

/** Plan week holding `today`: 0 before week 1, past the last week after the plan. */
export function weekOf(start, today) {
  return Math.floor(daysBetween(start, today) / 7) + 1;
}

/** Session kind in Chinese; a race named parkrun reads "parkrun". */
const kindOf = (s) => (/parkrun/i.test(s.name) ? "parkrun" : KIND[s.planned?.kind] ?? "课");

/** "5K W2 Tue 2x1.6km @T" -> "2x1.6km @T". */
const shortName = (name) => name.replace(/^5K W\d+ \w{3} /, "");

function title(text, sub) {
  return h("div", { class: "ws-title" }, h("h2", {}, text), sub ? h("div", { class: "small muted num" }, sub) : null);
}

function links() {
  return h("div", { class: "ws-links small" },
    h("a", { href: "#/review" }, "计划复盘 →"), h("a", { href: "#/plan" }, "8 周课表 →"));
}

function render(r) {
  if (!r.start || !r.sessions.length) {
    return [title("本周"),
      h("p", { class: "ws-empty" }, "还没有推送到 Garmin 的 5K 计划。",
        h("a", { href: "#/plan" }, "去看 8 周课表 →"))];
  }
  const weeks = Math.max(...r.sessions.map((s) => s.week));
  const n = weekOf(r.start, r.today);
  if (n < 1) {
    return [title("本周", `计划第 1 周从 ${r.start.slice(5)} 开始`), nextLine(r.sessions), links()];
  }
  if (n > weeks) {
    const t = r.totals;
    return [title("本周", `${weeks} 周计划已结束`),
      h("p", { class: "ws-next" }, `跑了 ${t.done}/${t.sessions} 节，${t.done_km.toFixed(1)}/${t.planned_km.toFixed(1)} km。`),
      links()];
  }
  const monday = addDays(r.start, (n - 1) * 7);
  const these = r.sessions.filter((s) => s.week === n);
  const done = these.filter((s) => s.status === "done");
  const doneKm = done.reduce((a, s) => a + (s.actual?.dist_m ?? 0) / 1000, 0);
  const planKm = these.reduce((a, s) => a + (s.planned?.km ?? 0), 0);
  return [
    title(`本周 · 第 ${n}/${weeks} 周`, `${monday.slice(5)} – ${addDays(monday, 6).slice(5)}`),
    h("ol", { class: "ws-days" }, ...these.map(dayCell)),
    h("div", { class: "ws-sum" },
      h("div", { class: "num" }, h("b", {}, `${done.length}/${these.length}`), " 节"),
      h("div", { class: "small muted num" }, `${doneKm.toFixed(1)} / ${planKm.toFixed(1)} km`)),
    h("div", { class: "ws-side" }, nextLine(r.sessions), links()),
  ];
}

function dayCell(s) {
  return h("li", { class: `ws-day st-${s.status}` },
    h("div", { class: "small muted num" }, dayLabel(s.date)),
    h("div", { class: "ws-kind" }, kindOf(s)),
    h("div", { class: "small num" }, s.planned ? `${s.planned.km} km` : ""),
    h("div", { class: "ws-st small" }, STATUS[s.status]));
}

function nextLine(sessions) {
  const next = sessions.find((s) => s.status === "today" || s.status === "upcoming");
  if (!next) return null;
  const km = next.planned ? ` · ${next.planned.km} km` : "";
  return h("p", { class: "ws-next" }, h("span", { class: "muted" }, "下一节 "),
    h("b", { class: "num" }, dayLabel(next.date)), ` ${kindOf(next)} ${shortName(next.name)}${km}`);
}
