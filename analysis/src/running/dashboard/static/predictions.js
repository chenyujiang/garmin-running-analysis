// Race predictions, column 3 of the top band (ticket 14). Reads GET /api/predictions.
// Prototype variant A: a small table, main prediction (VDOT; marathon = Vickers 2016)
// with Riegel and Garmin as comparison columns, the basis race written underneath.
// Stale (no all-out race in 6 months): the table fades, a red line gives the
// last race date and asks for races.csv to be updated.

import { h, fmtDate } from "./dom.js";

const TITLE = "成绩预测";

/** The section element; it fills itself once the data arrives. */
export function predictionsSection() {
  const section = h("section", { class: "band-predict" }, h("h2", {}, TITLE),
    h("p", { class: "small muted" }, "正在读取…"));
  load(section);
  return section;
}

async function load(section) {
  const today = new URLSearchParams(location.search).get("today");
  let v;
  try {
    const r = await fetch(today ? `api/predictions?today=${encodeURIComponent(today)}` : "api/predictions");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    v = await r.json();
  } catch (err) {
    section.replaceChildren(h("h2", {}, TITLE), h("p", { class: "warn" }, `无法读取成绩预测：${err.message}`));
    return;
  }
  section.replaceChildren(...render(v));
}

const pad = (n) => String(n).padStart(2, "0");

export function fmtTime(s) {
  if (s == null) return "—";
  const t = Math.round(s);
  const hh = Math.floor(t / 3600);
  const mm = Math.floor((t % 3600) / 60);
  return hh ? `${hh}:${pad(mm)}:${pad(t % 60)}` : `${mm}:${pad(t % 60)}`;
}

export function fmtDistance(m) {
  if (Math.abs(m - 42195) < 1) return "全马";
  if (Math.abs(m - 21097.5) < 1) return "半马";
  return m % 1000 === 0 ? `${m / 1000}K` : `${(m / 1000).toFixed(1)} km`;
}

const MAIN_LABEL = { vdot: "VDOT", vickers_model1: "Vickers", vickers_model2: "Vickers" };

function render(v) {
  const out = [h("h2", {}, TITLE)];
  if (v.races_error) out.push(h("p", { class: "warn small" }, v.races_error.message));
  if (v.stale && !v.races_error) {
    out.push(h("p", { class: "warn small" },
      v.last_race_date
        ? `最近一场全力比赛是 ${fmtDate(v.last_race_date)}，已超过 6 个月，不给预测。比赛后请更新 races.csv。`
        : "races.csv 里还没有全力比赛（all_out = yes），不给预测。比赛后请更新 races.csv。"));
  }
  out.push(table(v), basis(v), h("div", { class: "foot" }, how(v)));
  return out;
}

function table(v) {
  return h("table", { class: v.stale ? "predict stale" : "predict" },
    h("thead", {}, h("tr", {},
      h("th", {}, ""),
      h("th", { class: "r" }, "预测"),
      h("th", { class: "r" }, `Riegel${v.riegel_k ? ` ${v.riegel_k.toFixed(2)}` : ""}`),
      h("th", { class: "r" }, "Garmin"),
    )),
    h("tbody", {}, ...v.rows.map((r) => h("tr", {},
      h("td", {}, r.label),
      h("td", { class: "r main", title: r.predicted_method ? MAIN_LABEL[r.predicted_method] : "" },
        fmtTime(r.predicted_s),
        r.predicted_method && r.predicted_method !== "vdot" ? h("sup", {}, "V") : null),
      h("td", { class: "r" }, fmtTime(r.riegel_s)),
      h("td", { class: "r" }, fmtTime(r.garmin_s)),
    ))),
  );
}

function basis(v) {
  if (!v.basis) {
    return v.garmin
      ? h("p", { class: "small muted" }, `Garmin 列为 ${fmtDate(v.garmin.date)} 的 Race Predictor。`)
      : null;
  }
  const b = v.basis;
  const parts = [
    `依据 ${fmtDate(b.date)} ${fmtDistance(b.distance_m)} ${fmtTime(b.time_s)}`,
    b.note ? `（${b.note}）` : "",
    `，VDOT ${b.vdot.toFixed(1)}。`,
    `全马（V）用 Vickers 2016，近 8 周平均每周 ${v.weekly_km.toFixed(1)} km`,
    v.vickers_races.length === 2
      ? `，并用 ${fmtDistance(v.vickers_races[1].distance_m)} ${fmtDate(v.vickers_races[1].date)} 定指数。`
      : "。",
    v.riegel_k_source === "personal" ? "Riegel 指数由多场比赛拟合。" : "Riegel 用默认指数 1.06。",
    v.garmin ? `Garmin 为 ${fmtDate(v.garmin.date)} 的值。` : "",
  ];
  return h("p", { class: "small muted basis" }, parts.join(""));
}

function how(v) {
  const p = v.method.params;
  return h("details", { class: "how" },
    h("summary", {}, "预测怎么算的"),
    h("div", { class: "body" },
      h("p", {}, v.method.description),
      h("p", { class: "muted" },
        `当前参数：窗口 ${p.window_months} 个月，周跑量取 ${p.volume_weeks} 周，`
        + `Riegel 默认 k = ${p.riegel_k_default}，个人 k 截断在 [${p.riegel_k_range.join(", ")}]。`
        + `本次周跑量 ${v.weekly_km.toFixed(1)} km = ${v.weekly_miles.toFixed(1)} 英里。`),
    ),
  );
}
