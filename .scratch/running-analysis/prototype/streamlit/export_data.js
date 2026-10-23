// PROTOTYPE: dump the synthetic data of ../dashboard.html to data-*.json for app.py.
// Run from this directory: node export_data.js
const fs = require("fs");
const html = fs.readFileSync("../dashboard.html", "utf8");
const core = html.slice(html.indexOf("const DAY"), html.indexOf("const HOW"));
eval(core + `
for (const st of ["normal", "stale"]) {
  const D = genData(st), V = view(D);
  const out = {
    days: D.days.map(x => ({ ...x, d: ymd(x.d) })), weeks: D.weeks.map(x => ({ ...x, d: ymd(x.d) })),
    races: D.races.map(r => ({ ...r, date: ymd(r.date) })), longRuns: D.longRuns.map(x => ({ ...x, d: ymd(x.d) })),
    pred: { ...D.pred, basis: { ...D.pred.basis, date: ymd(D.pred.basis.date) } },
    view: { ratio: V.ratio, onset: V.onset && ymd(V.onset), newRuns: V.newRuns, tsbWord: V.tsbWord, roll7: V.roll7,
      aerNow: { d: ymd(V.aerNow.d), aerRoll: V.aerNow.aerRoll }, aerYearAgo: { d: ymd(V.aerYearAgo.d), aerRoll: V.aerYearAgo.aerRoll } },
  };
  fs.writeFileSync("data-" + st + ".json", JSON.stringify(out));
}`);
