// Activity list page, #/runs (run-detail ticket 01). Reads GET /api/activities.
// Prototype variant A table. Filters and page live in the hash query
// (#/runs?type=all&min_km=10&page=2), so a filtered list can be bookmarked.

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

/** Filters from the hash query; anything invalid falls back to the default. */
function readQuery(query) {
  const type = query.get("type") === "all" ? "all" : "running";
  const km = Number.parseFloat(query.get("min_km"));
  const page = Number.parseInt(query.get("page"), 10);
  return {
    type,
    min_km: Number.isFinite(km) && km > 0 ? km : null,
    page: Number.isInteger(page) && page >= 1 ? page : 1,
  };
}

function hashFor(f) {
  const q = new URLSearchParams();
  if (f.type !== "running") q.set("type", f.type);
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
    h("h1", { class: "headline" }, "全部活动"),
    h("div", { class: "tools" }, typeSwitch(f), distanceSelect(f)),
  );
}

function typeSwitch(f) {
  const button = (type, label) => {
    const b = h("button", { type: "button", "aria-pressed": String(f.type === type) }, label);
    b.addEventListener("click", () => { location.hash = hashFor({ ...f, type, page: 1 }); });
    return b;
  };
  return h("div", { class: "seg", role: "group", "aria-label": "活动类型" },
    button("running", "跑步类"),
    button("all", "全部类型"),
  );
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
  const q = new URLSearchParams({ type: f.type, page: String(f.page), page_size: String(PAGE_SIZE) });
  if (f.min_km != null) q.set("min_km", String(f.min_km));
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
    const msg = v.total ? "这一页没有活动。" : "没有符合筛选条件的活动。";
    return [h("p", { class: "small muted" }, msg), pager(v, f), how(v.method)];
  }
  return [
    h("p", { class: "small muted count" }, `共 ${v.total} 个活动`),
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
