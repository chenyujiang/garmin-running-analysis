// Activity list page, #/runs (run-detail ticket 01). Reads GET /api/activities.
// Prototype variant A table. Running types only. Search, filters and page
// live in the hash query (#/runs?q=parkrun&from=2026-01-01&to=2026-06-30&
// min_km=10&page=2), so a search can be bookmarked.

import { h, fmtDate, fmtDur, fmtPace } from "./dom.js";

const PAGE_SIZE = 50;
const DISTANCES = [null, 5, 10, 15, 21, 30];

const TYPE_NAMES = {
  running: "跑步",
  street_running: "路跑",
  track_running: "田径场",
  treadmill_running: "跑步机",
  indoor_running: "室内跑",
  trail_running: "越野跑",
  ultra_run: "超马",
  obstacle_run: "障碍跑",
  virtual_run: "虚拟跑",
  cycling: "骑行",
  walking: "步行",
  hiking: "徒步",
  strength_training: "力量",
  lap_swimming: "泳池游泳",
  open_water_swimming: "公开水域游泳",
};

/** Garmin type key shown in Chinese when known, else as is. */
export function typeName(key) {
  return TYPE_NAMES[key] ?? key;
}

const isDate = (s) => /^\d{4}-\d{2}-\d{2}$/.test(s ?? "");

/** Filters from the hash query; anything invalid falls back to the default. */
function readQuery(query) {
  const km = Number.parseFloat(query.get("min_km"));
  const page = Number.parseInt(query.get("page"), 10);
  return {
    q: (query.get("q") ?? "").trim(),
    from: isDate(query.get("from")) ? query.get("from") : null,
    to: isDate(query.get("to")) ? query.get("to") : null,
    min_km: Number.isFinite(km) && km > 0 ? km : null,
    page: Number.isInteger(page) && page >= 1 ? page : 1,
  };
}

function hashFor(f) {
  const q = new URLSearchParams();
  if (f.q) q.set("q", f.q);
  if (f.from) q.set("from", f.from);
  if (f.to) q.set("to", f.to);
  if (f.min_km != null) q.set("min_km", String(f.min_km));
  if (f.page > 1) q.set("page", String(f.page));
  const s = q.toString();
  return s ? `#/runs?${s}` : "#/runs";
}

/** The list page. `query` is the URLSearchParams after "#/runs?". */
export function runsPage(query) {
  const f = readQuery(query);
  const section = h("section", { class: "runs" }, head(f), h("p", { class: "small muted" }, "正在读取…"));
  load(section, f);
  return section;
}

function head(f) {
  return h("div", { class: "sec-head" },
    h("h1", { class: "headline" }, "全部跑步"),
    h("div", { class: "tools" }, searchForm(f), distanceSelect(f)),
  );
}

/** Name keyword plus a date range; submitting (Enter or the button) searches. */
function searchForm(f) {
  const text = h("input", { type: "search", value: f.q, placeholder: "搜名称，如 parkrun",
    "aria-label": "按名称搜索", size: "16" });
  const from = h("input", { type: "date", value: f.from ?? "", "aria-label": "开始日期" });
  const to = h("input", { type: "date", value: f.to ?? "", "aria-label": "结束日期" });
  const form = h("form", { class: "runs-search", role: "search" },
    text, from, h("span", { class: "muted" }, "–"), to,
    h("button", { type: "submit" }, "搜索"),
    f.q || f.from || f.to ? h("a", { href: hashFor({ min_km: f.min_km, page: 1 }), class: "small" }, "清除") : null,
  );
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    location.hash = hashFor({
      ...f, q: text.value.trim(), from: from.value || null, to: to.value || null, page: 1,
    });
  });
  return form;
}

function distanceSelect(f) {
  const options = DISTANCES.includes(f.min_km) ? DISTANCES : [...DISTANCES, f.min_km];
  const select = h("select", { "aria-label": "最小距离" },
    ...options.map((km) => {
      const o = h("option", { value: km == null ? "" : String(km) }, km == null ? "不限距离" : `≥ ${km} km`);
      if (km === f.min_km) o.selected = true;
      return o;
    }),
  );
  select.addEventListener("change", () => {
    const km = select.value === "" ? null : Number.parseFloat(select.value);
    location.hash = hashFor({ ...f, min_km: km, page: 1 });
  });
  return select;
}

async function load(section, f) {
  const q = new URLSearchParams({ page: String(f.page), page_size: String(PAGE_SIZE) });
  if (f.min_km != null) q.set("min_km", String(f.min_km));
  if (f.q) q.set("q", f.q);
  if (f.from) q.set("date_from", f.from);
  if (f.to) q.set("date_to", f.to);
  let v;
  try {
    const r = await fetch(`api/activities?${q}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    v = await r.json();
  } catch (err) {
    section.replaceChildren(head(f), h("p", { class: "warn" }, `无法读取活动列表：${err.message}`));
    return;
  }
  section.replaceChildren(head(f), ...render(v, f));
}

function render(v, f) {
  if (!v.activities.length) {
    const msg = v.total ? "这一页没有活动。" : "没有符合条件的跑步。";
    return [h("p", { class: "small muted" }, msg), pager(v, f), how(v.method)];
  }
  return [
    h("p", { class: "small muted count" }, `${f.q || f.from || f.to ? "找到" : "共"} ${v.total} 次跑步`),
    table(v.activities),
    h("div", { class: "foot" }, pager(v, f), how(v.method)),
  ];
}

function table(rows) {
  return h("table", { class: "runs-table" },
    h("thead", {}, h("tr", {},
      h("th", {}, "日期"),
      h("th", {}, "类型"),
      h("th", {}, "名称"),
      h("th", { class: "r" }, "距离"),
      h("th", { class: "r" }, "时长"),
      h("th", { class: "r", title: "只算跑的秒，走路不计" }, "跑步配速"),
      h("th", { class: "r" }, "平均心率"),
    )),
    h("tbody", {}, ...rows.map(row)),
  );
}

function row(a) {
  const link = (text) => h("a", { href: `#/run/${a.activity_id}` }, text);
  return h("tr", {},
    h("td", {}, link(`${fmtDate(a.start_time_local)} ${a.start_time_local.slice(11, 16)}`)),
    h("td", {}, typeName(a.activity_type)),
    h("td", { class: "name" }, link(a.activity_name || "（未命名）")),
    h("td", { class: "r" }, a.distance_m == null ? "—" : `${(a.distance_m / 1000).toFixed(2)} km`),
    h("td", { class: "r" }, a.duration_s == null ? "—" : fmtDur(a.duration_s)),
    h("td", { class: "r" }, a.running_pace_s_per_km == null ? "—" : `${fmtPace(a.running_pace_s_per_km)} /km`),
    h("td", { class: "r" }, a.avg_hr_bpm == null ? "—" : `${Math.round(a.avg_hr_bpm)}`),
  );
}

function pager(v, f) {
  const pages = Math.max(1, Math.ceil(v.total / v.page_size));
  if (pages <= 1) return null;
  const go = (page, label, disabled) => disabled
    ? h("span", { class: "muted" }, label)
    : h("a", { href: hashFor({ ...f, page }) }, label);
  return h("nav", { class: "pager small", "aria-label": "分页" },
    go(f.page - 1, "← 上一页", f.page <= 1),
    h("span", {}, `第 ${f.page} / ${pages} 页`),
    go(f.page + 1, "下一页 →", f.page >= pages),
  );
}

function how(method) {
  return h("details", { class: "how" },
    h("summary", {}, "怎么算的"),
    h("div", { class: "body" }, h("p", {}, method.description)),
  );
}
