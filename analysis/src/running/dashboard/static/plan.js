// 5K plan page, #/plan. Reads GET /api/plan5k: an 8-week plan towards a 5K
// goal (default 20:00) after Jack Daniels' VDOT method. Paces come from the
// current VDOT (races.csv basis, a recent parkrun, or the 5K time typed into
// the form). Form state lives in the hash:
// #/plan?current=21:30&target=20:00&days=2,3,4,6&parkrun=6 (parkrun=0: none).
// `p.push` lists the sessions the last `running-push-plan --apply` put on the
// Garmin calendar; those rows get their date and an "已推送" tag.

import { h, fmtDur, fmtPace } from "./dom.js";

const DAYS = ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"];
const KIND = { E: "E 跑", L: "长距离", Q: "质量课", rest: "休息", race: "比赛", parkrun: "parkrun" };
const PACES = [
  ["E", "轻松跑 / 长距离", "有氧基础、恢复；占周跑量大头"],
  ["M", "马拉松配速", "本计划不单练，作参照"],
  ["T", "乳酸阈", "舒服地吃力，约能持续 1 小时的强度"],
  ["I", "间歇", "最大摄氧，单组 3–5 分钟"],
  ["R", "重复跑", "速度与跑姿，组间充分恢复"],
];
const FEASIBILITY = {
  close: ["good", "差距 ≤ 1 VDOT，8 周可以拿下"],
  stretch: ["stretch", "差距 1–3 VDOT，需要 8 周练满"],
  far: ["far", "差距 > 3 VDOT，8 周内偏难"],
};

/** "21:30" -> 1290; anything else -> null. */
export function parseTime(text) {
  const m = /^\s*(\d{1,2}):([0-5]\d)\s*$/.exec(text ?? "");
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
}

export function planPage(query) {
  const root = h("div", { class: "plan" }, h("p", { class: "loading" }, "正在生成计划…"));
  load(root, query);
  return root;
}

async function load(root, query) {
  const params = new URLSearchParams();
  const today = new URLSearchParams(location.search).get("today");
  if (today) params.set("today", today);
  const current = parseTime(query.get("current"));
  const target = parseTime(query.get("target")) ?? 1200;
  if (current) params.set("current_s", current);
  params.set("target_s", target);
  if (query.get("days")) params.set("days", query.get("days"));
  if (query.get("parkrun")) params.set("parkrun_day", query.get("parkrun"));
  let p;
  try {
    const r = await fetch(`api/plan5k?${params}`);
    if (!r.ok) {
      const detail = (await r.json().catch(() => null))?.detail;
      throw new Error(typeof detail === "string" ? detail : `HTTP ${r.status}`);
    }
    p = await r.json();
  } catch (err) {
    root.replaceChildren(h("p", { class: "warn" }, `无法生成计划：${err.message}`));
    return;
  }
  root.replaceChildren(...render(p, query));
}

const paceOf = (paces, key) => ({ T: paces.t, I: paces.i, R: paces.r, M: paces.m }[key]);
const chip = (key) => h("span", { class: `pk pk-${key}` }, key);

function render(p, query) {
  return [
    head(p),
    form(p, query),
    ...p.warnings.map((w) => h("p", { class: "warn" }, w)),
    paceTable(p),
    h("h2", { class: "plan-h" }, "8 周课表"),
    h("p", { class: "small muted" }, layoutText(p)),
    pushText(p.push),
    ...p.weeks.map((w) => weekBlock(w, p.push)),
    rules(),
  ];
}

function layoutText(p) {
  const days = p.days.map((d) => DAYS[d]).join("、");
  const caps = "组数已按 Daniels 的上限（T ≤ 周量 10%，I ≤ 8%，R ≤ 5%）裁剪。";
  const qc = "质量课含 3 km E 热身和 2 km E 放松，公里数已算进去。";
  if (p.parkrun_day) {
    return `跑步日：${days}。${DAYS[p.parkrun_day]} parkrun 当作每周的 I 课（含 2 km 热身、1.5 km 放松），` +
      `离它最远的一天做 T + R 质量课，其余是 E 跑。第 8 周的 parkrun 就是目标赛。${qc}${caps}`;
  }
  return `跑步日：${days}。两次质量课互相隔开，最后一个跑步日是长距离，第 8 周那天比赛。${qc}${caps}`;
}

/** "2026-11-10" -> "11-10". */
const monthDay = (iso) => iso.slice(5);

function pushText(push) {
  if (!push) return null;
  const n = push.sessions.length;
  const at = push.pushed_at_utc ? `（推送于 ${new Date(push.pushed_at_utc).toLocaleString("zh-CN")}）` : "";
  const text = [`Garmin 日历上有上次推送的 ${push.total} 节计划课，第 1 周从 ${push.start} 开始${at}。`];
  if (n === push.total) {
    text.push("下面每节都已推送。");
  } else {
    text.push(`其中 ${n} 节与这页的计划一致，已在下面标出；其余是按别的设置推送的。`,
      "要换成这页的计划，用 running-push-plan --apply --replace。");
  }
  text.push(" ");
  return h("p", { class: "small push-note" }, ...text, h("a", { href: "#/review" }, "看计划复盘 →"));
}

function head(p) {
  const c = p.current;
  const [tone, label] = FEASIBILITY[p.feasibility];
  const source = {
    races: `races.csv：${c.basis_date} ${(c.basis_distance_m / 1000).toFixed(1)} km ${fmtDur(c.basis_time_s)}`,
    parkrun: `近 8 周最好的 parkrun：${c.basis_date} ${(c.basis_distance_m / 1000).toFixed(2)} km ${fmtDur(c.basis_time_s)}`,
    override: "按你输入的 5K 成绩",
    assumed: "无近期比赛，按假设",
  }[c.source];
  return h("header", { class: "plan-head" },
    h("h1", { class: "headline" }, `5K 跑进 ${fmtDur(p.target_s)}：8 周计划`),
    h("p", { class: "dek" }, p.parkrun_day ? `在 ${DAYS[p.parkrun_day]}的 parkrun 里跑进 ${fmtDur(p.target_s)}。` : "",
      "按 Jack Daniels 的 VDOT 方法：用当前水平定配速，不用目标配速训练；",
      "练满 4 周、课都跑得住，再把训练 VDOT 提高 1。"),
    h("div", { class: "plan-nums" },
      num("当前 VDOT", c.vdot.toFixed(1), `相当 5K ${fmtDur(c.five_k_s)} · ${source}`),
      num("目标 VDOT", p.target_vdot.toFixed(1), `5K ${fmtDur(p.target_s)}`, "goal"),
      num("差距", `${p.gap_vdot > 0 ? "+" : ""}${p.gap_vdot.toFixed(1)}`, null, null,
        h("span", { class: `feas feas-${tone}` }, label)),
      num("计划周跑量", `${p.base_km.toFixed(0)} km`, `近 8 周平均 ${p.weekly_km_recent.toFixed(0)} km`),
    ),
    p.interim_target_s
      ? h("p", { class: "small" }, "建议中间目标：5K ", h("b", {}, fmtDur(p.interim_target_s)), "（当前 VDOT + 2）。")
      : null,
  );
}

function num(label, value, sub, tone, extra) {
  return h("div", { class: "plan-num" },
    h("div", { class: "small muted" }, label),
    h("div", { class: `big${tone ? ` tone-${tone}` : ""}` }, value),
    sub ? h("div", { class: "small muted" }, sub) : null,
    extra ?? null);
}

function form(p, query) {
  const cur = h("input", { name: "current", placeholder: "如 21:30", size: "6",
    value: query.get("current") ?? "", inputmode: "numeric" });
  const tgt = h("input", { name: "target", size: "6", value: query.get("target") ?? fmtDur(p.target_s) });
  const boxes = [1, 2, 3, 4, 5, 6, 7].map((d) => {
    const box = h("input", { type: "checkbox", value: String(d) });
    box.checked = p.days.includes(d);
    return [d, box];
  });
  const pr = h("select", { name: "parkrun" },
    h("option", { value: "0" }, "不跑"),
    ...[1, 2, 3, 4, 5, 6, 7].map((d) => h("option", { value: String(d) }, DAYS[d])));
  pr.value = String(p.parkrun_day ?? 0);
  const f = h("form", { class: "plan-form small" },
    h("label", {}, "当前 5K 成绩 ", cur),
    h("label", {}, "目标 ", tgt),
    h("span", { class: "plan-days" }, "跑步日 ",
      ...boxes.map(([d, box]) => h("label", {}, box, DAYS[d].slice(1)))),
    h("label", {}, "parkrun ", pr),
    h("button", { type: "submit" }, "重新计算"),
    h("span", { class: "muted" },
      "留空当前成绩则用 races.csv 里近 6 个月最好的全力比赛，或近 8 周最好的 parkrun，取较高者。"));
  f.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = new URLSearchParams();
    if (parseTime(cur.value)) q.set("current", cur.value.trim());
    if (parseTime(tgt.value)) q.set("target", tgt.value.trim());
    const days = boxes.filter(([, box]) => box.checked).map(([d]) => d);
    q.set("days", days.join(","));
    q.set("parkrun", pr.value);
    location.hash = `#/plan?${q}`;
  });
  return f;
}

function paceTable(p) {
  const later = p.weeks[p.weeks.length - 1].paces;
  const now = p.paces_now;
  const differs = Math.abs(later.vdot - now.vdot) > 0.05;
  const cell = (paces, key) => key === "E"
    ? `${fmtPace(paces.e_fast)}–${fmtPace(paces.e_slow)}`
    : fmtPace(paceOf(paces, key));
  const per400 = (paces, key) => (key === "I" || key === "R" ? `${Math.round(paceOf(paces, key) * 0.4)} 秒` : "");
  return h("section", { class: "plan-paces" },
    h("h2", { class: "plan-h" }, "训练配速"),
    h("table", {},
      h("thead", {}, h("tr", {},
        h("th", {}, ""), h("th", {}, "用途"),
        h("th", { class: "r" }, `第 1–4 周 /km（VDOT ${now.vdot.toFixed(1)}）`),
        h("th", { class: "r" }, "每 400 m"),
        differs ? h("th", { class: "r" }, `第 5–8 周 /km（VDOT ${later.vdot.toFixed(1)}）`) : null,
        h("th", { class: "r muted" }, `目标水平 /km（VDOT ${p.paces_goal.vdot.toFixed(1)}）`))),
      h("tbody", {}, ...PACES.map(([k, name, what]) => h("tr", {},
        h("td", {}, chip(k)),
        h("td", {}, name, h("div", { class: "small muted" }, what)),
        h("td", { class: "r num" }, cell(now, k)),
        h("td", { class: "r num" }, per400(now, k)),
        differs ? h("td", { class: "r num" }, cell(later, k)) : null,
        h("td", { class: "r num muted" }, cell(p.paces_goal, k)))))),
    h("p", { class: "small muted" },
      `目标 5K 配速 ${fmtPace(p.target_s / 5)}/km。按 Daniels，训练按当前水平的配速跑；目标列只作参照，提前按它练容易过量。`));
}

function partText(part, paces) {
  const per = paceOf(paces, part.pace) * part.dist_m / 1000;
  const d = part.dist_m >= 1000 ? `${part.dist_m / 1000} km` : `${part.dist_m} m`;
  const n = part.reps > 1 ? `${part.reps}×${d}` : d;
  const rest = part.rest ? `，间歇 ${part.rest}` : "";
  return [chip(part.pace), ` ${n}，每组 ${fmtDur(per)}${rest}`];
}

function sessionRow(s, paces, pushedOn) {
  let content;
  if (s.kind === "Q") {
    content = [h("div", {}, ...s.parts.flatMap((part, i) => [i ? h("br") : null, ...partText(part, paces)]))];
  } else if (s.kind === "E" || s.kind === "L") {
    content = [chip("E"), ` ${s.title}，${fmtPace(paces.e_fast)}–${fmtPace(paces.e_slow)}/km`];
  } else if (s.kind === "race" || s.kind === "parkrun") {
    content = [h("b", {}, s.title)];
    if (s.target_s) {
      content.push(` 目标 `, h("b", { class: "tone-goal" }, fmtDur(s.target_s)),
        `（${fmtPace(s.target_s / 5)}/km）`);
    }
  } else {
    content = [h("span", { class: "muted" }, s.title)];
  }
  if (s.note) content.push(h("div", { class: "small muted" }, s.note));
  return h("tr", { class: `k-${s.kind}${pushedOn ? " pushed" : ""}` },
    h("td", { class: "day" }, DAYS[s.day],
      pushedOn ? h("div", { class: "small muted num" }, monthDay(pushedOn)) : null),
    h("td", { class: "kind" }, KIND[s.kind],
      pushedOn ? h("div", {}, h("span", { class: "pushed-tag", title: `已在 Garmin 日历 ${pushedOn}` }, "已推送")) : null),
    h("td", {}, ...content),
    h("td", { class: "r num" }, s.km ? `${s.km} km` : ""));
}

function weekBlock(w, push) {
  const on = new Map((push?.sessions ?? []).filter((x) => x.week === w.n).map((x) => [x.day, x.date]));
  return h("section", { class: "plan-week" },
    h("h3", {}, `第 ${w.n} 周`,
      h("span", { class: "muted" }, ` · ${w.phase} · 约 ${w.km} km · 训练 VDOT ${w.vdot.toFixed(1)}`)),
    h("table", {}, h("tbody", {}, ...w.sessions.map((s) => sessionRow(s, w.paces, on.get(s.day))))));
}

function rules() {
  return h("section", { class: "plan-rules" },
    h("h2", { class: "plan-h" }, "执行要点"),
    h("ul", {},
      h("li", {}, "质量课跑不完或配速掉得厉害：下次照旧用这一档配速，不要硬提。"),
      h("li", {}, "第 5 周起训练 VDOT 提高 1 的前提，是前 4 周的 I 和 T 课都跑得稳；否则继续用原配速。"),
      h("li", {}, "错过一次质量课就跳过，不要挤到第二天连做。生病或伤痛时先停质量课，只跑 E。"),
      h("li", {}, "E 跑宁慢勿快；心率和感觉比配速优先。"),
      h("li", {}, "parkrun 按表上的目标时间均匀跑，别被前面的人带快；第 1 km 最容易超速。"),
      h("li", {}, "parkrun 后一天只跑 E 或休息；腿还沉就把周二的质量课减一组。"),
      h("li", {}, "比赛后把成绩记进 races.csv（all_out = yes），这页会用新的 VDOT 重新算。"),
    ),
    h("p", { class: "small muted" }, "方法依据：Jack Daniels《Daniels' Running Formula》的 VDOT 配速与质量课上限；8 周编排为本工具按其原则排出的简化版。"));
}
