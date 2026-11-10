// Plan review page, #/review. Reads GET /api/plan-review: every session the
// last `running-push-plan --apply` put on the Garmin calendar, with the run of
// that day judged against the planned steps. Run sessions come newest first,
// then the next few to run. Warm-up and cool-down are listed but never count
// against a session.

import { h, fmtDur, fmtPace } from "./dom.js";
import { how } from "./run.js";

const WEEKDAY = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
const STATUS = { done: "已跑", missed: "未跑", today: "今天，尚未同步", upcoming: "待跑" };
const VERDICT = { good: "好", neutral: "—", watch: "注意" };
const REP = { ok: "区间内", fast: "偏快", slow: "偏慢", extra: "计划外" };
const UPCOMING = 5;

export function reviewPage() {
  const root = h("div", { class: "review" }, h("p", { class: "loading" }, "正在读取计划复盘…"));
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
    root.replaceChildren(h("p", { class: "warn" }, `无法读取计划复盘：${err.message}`));
    return;
  }
  root.replaceChildren(...render(r));
}

/** "2026-11-10" -> "11-10 周二". */
export function dayLabel(iso) {
  const d = new Date(`${iso}T00:00:00`);
  return `${iso.slice(5)} ${WEEKDAY[d.getDay()]}`;
}

const km = (m) => `${(m / 1000).toFixed(1)} km`;
const range = (p) => `${fmtPace(p.fast)}–${fmtPace(p.slow)}`;

function render(r) {
  const past = r.sessions.filter((s) => s.status !== "upcoming").reverse();
  const next = r.sessions.filter((s) => s.status === "upcoming").slice(0, UPCOMING);
  return [
    h("header", { class: "plan-head" },
      h("h1", { class: "headline" }, "计划复盘"),
      h("p", { class: "dek" },
        r.start
          ? `推送到 Garmin 的 5K 计划，第 1 周从 ${r.start} 开始。每次同步后，跑过的课会和计划逐段对比。热身和放松跑短了不算未完成。`
          : "推送 5K 计划到 Garmin 之后，这里会逐节对比计划和实际。"),
      h("div", { class: "tools" }, how(r.method))),
    ...r.warnings.map((w) => h("p", { class: "warn" }, w)),
    r.totals ? totals(r.totals) : null,
    ...past.map(card),
    next.length ? upcoming(next) : null,
  ].filter(Boolean);
}

function totals(t) {
  const item = (label, value, sub) =>
    h("div", { class: "plan-num" },
      h("div", { class: "small muted" }, label),
      h("div", { class: "big" }, value),
      sub ? h("div", { class: "small muted" }, sub) : null);
  return h("div", { class: "plan-nums" },
    item("已跑", `${t.done}/${t.past}`, t.missed ? `漏了 ${t.missed} 节` : "到今天没有漏课"),
    item("质量课配速达标", `${t.quality_on_pace}/${t.quality_done}`, "每组都在区间内"),
    item("跑量", `${t.done_km} km`, `计划 ${t.planned_km} km（含热身放松）`),
    item("计划共", `${t.sessions} 节`, `还剩 ${t.sessions - t.past} 节`));
}

function card(s) {
  const a = s.actual;
  const title = h("h2", {}, `${dayLabel(s.date)} · `, h("span", { class: "wo" }, s.name));
  const tag = h("span", { class: `rv-tag st-${s.status}${s.verdict ? ` v-${s.verdict}` : ""}` },
    s.status === "done" && s.verdict ? VERDICT[s.verdict] === "—" ? STATUS.done : VERDICT[s.verdict] : STATUS[s.status]);
  const link = a ? h("a", { href: `#/run/${a.activity_id}`, class: "small" }, "看这次跑步 →") : null;
  return h("section", { class: `rv-card st-${s.status}` },
    h("div", { class: "sec-head" }, title, tag, h("div", { class: "tools" }, link)),
    a ? overview(a) : missing(s),
    a && s.planned ? detail(s.planned, a) : null,
    s.notes.length ? notes(s.notes) : null,
  );
}

function missing(s) {
  const plan = s.planned ? `计划 ${s.planned.km} km。` : "";
  const text = s.status === "missed" ? "这天没有跑步记录。" : "同步后这里会出现对比。";
  return h("p", { class: "small muted" }, text, plan);
}

function overview(a) {
  const bits = [km(a.dist_m), fmtDur(a.time_s)];
  if (a.pace) bits.push(`${fmtPace(a.pace)}/km`);
  if (a.hr_avg) bits.push(`平均心率 ${Math.round(a.hr_avg)}`);
  const others = a.others ? `当天另有 ${a.others} 次跑步，按最长这次算。` : "";
  return h("p", { class: "rv-line" }, h("span", { class: "num" }, bits.join(" · ")),
    others ? h("span", { class: "small muted" }, ` ${others}`) : null);
}

function detail(p, a) {
  if (p.kind === "quality") return qualityTable(p, a);
  if (p.kind === "race" && a.effort) return raceTable(p, a.effort);
  return null;
}

function warmRow(label, plan, actualM) {
  if (!plan) return null;
  return h("tr", { class: "soft" },
    h("td", {}, label),
    h("td", {}, `${km(plan.dist_m)} @ ${range(plan)}`),
    h("td", { class: "r" }, actualM == null ? "—" : km(actualM)),
    h("td", {}), h("td", {}), h("td", {}), h("td", {}),
    h("td", { class: "small" }, "可缩短"));
}

function qualityTable(p, a) {
  const rows = [warmRow("热身", p.warmup, a.warmup_m)];
  p.parts.forEach((part, i) => {
    const reps = a.reps.filter((r) => r.part === i);
    for (let n = 1; n <= part.reps; n++) {
      const r = reps.find((x) => x.n === n);
      rows.push(h("tr", { class: r ? `rep-${r.verdict}` : "rep-missing" },
        h("td", {}, `第 ${i + 1} 段 ${n}/${part.reps}`),
        h("td", {}, `${part.dist_m} m @ ${range(part)}`),
        h("td", { class: "r" }, r ? `${Math.round(r.dist_m)} m` : "—"),
        h("td", { class: "r" }, r ? fmtDur(r.time_s) : ""),
        h("td", { class: "r num" }, r ? fmtPace(r.pace) : ""),
        h("td", { class: "r" }, r?.hr_avg ? `${Math.round(r.hr_avg)} / ${Math.round(r.hr_max)}` : ""),
        h("td", { class: "r" }, r?.rest_s != null ? fmtDur(r.rest_s) : ""),
        h("td", {}, r ? repVerdict(r) : "没找到")));
    }
  });
  for (const r of a.reps.filter((x) => x.part == null)) {
    rows.push(h("tr", { class: "soft" },
      h("td", {}, "计划外"), h("td", {}),
      h("td", { class: "r" }, `${Math.round(r.dist_m)} m`),
      h("td", { class: "r" }, fmtDur(r.time_s)),
      h("td", { class: "r num" }, fmtPace(r.pace)),
      h("td", { class: "r" }, r.hr_avg ? `${Math.round(r.hr_avg)} / ${Math.round(r.hr_max)}` : ""),
      h("td", { class: "r" }, r.rest_s != null ? fmtDur(r.rest_s) : ""),
      h("td", {}, REP.extra)));
  }
  rows.push(warmRow("放松", p.cooldown, a.cooldown_m));
  return h("table", { class: "rv-table" },
    h("thead", {}, h("tr", {},
      h("th", {}, ""), h("th", {}, "计划"), h("th", { class: "r" }, "距离"), h("th", { class: "r" }, "用时"),
      h("th", { class: "r" }, "配速"), h("th", { class: "r" }, "心率 均/高"), h("th", { class: "r" }, "组间"),
      h("th", {}, ""))),
    h("tbody", {}, ...rows.filter(Boolean)));
}

function repVerdict(r) {
  if (r.verdict === "ok") return REP.ok;
  return `${REP[r.verdict]} ${Math.round(r.off_s)} 秒`;
}

function raceTable(p, e) {
  const target = p.target_s ? p.target_s / 5 : null;
  const rows = e.splits.map((sp) =>
    h("tr", {},
      h("td", {}, `第 ${sp.km} km`),
      h("td", { class: "r num" }, fmtDur(sp.time_s)),
      h("td", { class: "r" }, target ? signed(sp.time_s - target) : ""),
      h("td", { class: "r" }, sp.hr_avg ? Math.round(sp.hr_avg) : "")));
  rows.push(h("tr", { class: "total" },
    h("td", {}, e.full ? "最快 5 km" : `全程 ${km(e.dist_m)}`),
    h("td", { class: "r num" }, `${fmtDur(e.time_s)}（${fmtPace(e.pace)}/km）`),
    h("td", { class: "r" }, p.target_s && e.full ? `计划 ${fmtDur(p.target_s)}` : ""),
    h("td", { class: "r" }, e.hr_avg ? Math.round(e.hr_avg) : "")));
  return h("table", { class: "rv-table" },
    h("thead", {}, h("tr", {},
      h("th", {}, ""), h("th", { class: "r" }, "用时"),
      h("th", { class: "r" }, target ? `比计划 ${fmtPace(target)}/km` : ""), h("th", { class: "r" }, "心率"))),
    h("tbody", {}, ...rows));
}

/** -4.2 -> "−4 秒", 3 -> "+3 秒". */
export function signed(s) {
  const n = Math.round(s);
  return `${n < 0 ? "−" : "+"}${Math.abs(n)} 秒`;
}

function notes(list) {
  return h("ul", { class: "rv-notes" },
    ...list.map((n) =>
      h("li", { class: `verdict-${n.verdict}` },
        h("span", { class: "verdict" }, VERDICT[n.verdict]),
        h("span", { class: "text" }, n.text))));
}

function upcoming(list) {
  return h("section", { class: "rv-next" },
    h("div", { class: "sec-head" }, h("h2", {}, "接下来")),
    h("table", {},
      h("tbody", {}, ...list.map((s) =>
        h("tr", {},
          h("td", {}, dayLabel(s.date)),
          h("td", {}, s.name),
          h("td", { class: "r" }, s.planned ? `${s.planned.km} km` : ""))))),
    h("p", { class: "small muted" }, h("a", { href: "#/plan" }, "完整课表 →")));
}
