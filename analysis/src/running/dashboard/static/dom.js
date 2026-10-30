// Small DOM and formatting helpers shared by the dashboard modules.

/** Create an element. Children may be strings (inserted as text) or nodes. */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  for (const c of children) {
    if (c == null) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const pad = (n) => String(n).padStart(2, "0");

/** UTC ISO timestamp ("2026-10-28T08:00:00Z") shown in the browser's local time. */
export function fmtDateTime(isoUtc) {
  const d = new Date(isoUtc);
  if (Number.isNaN(d.getTime())) return isoUtc;
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Local wall-clock timestamp without offset ("2026-10-20T07:00:00"), date part only. */
export function fmtDate(isoLocal) {
  return isoLocal.slice(0, 10);
}
