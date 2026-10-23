"""PROTOTYPE, throwaway (wayfinder ticket 08).

Streamlit rebuild of dashboard.html variant A, to judge whether Streamlit can carry the
"sports-page data graphics" design. Same synthetic data as the HTML version, exported to
data-*.json by `node export_data.js`.

Run:  uv run --with streamlit --with altair --with polars streamlit run app.py
"""

import json
import math
from datetime import date, timedelta
from pathlib import Path

import altair as alt
import polars as pl
import streamlit as st

HERE = Path(__file__).parent
PAPER, PAPER2, RULE, INK, INK2, INK3 = "#f3efe6", "#e9e3d6", "#d2c9b7", "#1c1a17", "#4a453d", "#6b6458"
RED, FIT, FAT, POS, TEMP, DOT = "#b0281f", "#1f3d63", "#a5641a", "#3f6b4f", "#a39a8a", "#8f8676"
SANS = '"IBM Plex Sans", "Noto Sans SC", sans-serif'

st.set_page_config(page_title="跑步记录", layout="wide")
state = st.query_params.get("state", "normal")
D = json.loads((HERE / f"data-{state}.json").read_text(encoding="utf-8"))
V = D["view"]
days = pl.DataFrame(D["days"]).with_columns(pl.col("d").str.to_date())
weeks = pl.DataFrame(D["weeks"]).with_columns(pl.col("d").str.to_date())
LAST = days["d"].max()

# Everything below this line is what Streamlit cannot express natively: fonts, headline
# colour, the red "changed" dot, table rules, spacing between blocks.
st.markdown(
    f"""
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600&family=Noto+Sans+SC:wght@400;700&family=Noto+Serif+SC:wght@600;900&display=swap" rel="stylesheet">
<style>
html, body, [class*="st-"], .stMarkdown {{ font-family: {SANS}; font-variant-numeric: tabular-nums; }}
.block-container {{ padding-top: 2rem; max-width: 1320px; }}
h1.hl {{ font: 900 30px/1.25 "Noto Serif SC", serif; color: {RED}; margin: 0 0 4px; padding: 0; }}
h2.sec {{ font: 600 19px/1.3 "Noto Serif SC", serif; margin: 0; padding: 0 0 6px; border-bottom: 1px solid {INK}; }}
.dek {{ color: {INK2}; margin: 0 0 10px; }}
.stat {{ display: flex; gap: 28px; }} .stat .l {{ display: block; font-size: 13px; color: {INK3}; }}
.big {{ font: 600 34px/1 {SANS}; position: relative; }}
.new::after {{ content: ""; position: absolute; top: 2px; right: -9px; width: 6px; height: 6px; border-radius: 50%; background: {RED}; }}
table.t {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
table.t th {{ font-weight: 400; font-size: 13px; color: {INK3}; text-align: left; border-bottom: 1px solid {INK}; padding: 6px 8px; }}
table.t td {{ border-bottom: 1px solid {RULE}; padding: 8px; }}
table.t .r {{ text-align: right; }}
.muted {{ color: {INK3}; font-size: 13px; }}
</style>""",
    unsafe_allow_html=True,
)


def fmt_dur(s):
    s = round(s)
    h, m, x = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{x:02d}" if h else f"{m}:{x:02d}"


def fmt_pace(s):
    return "—" if s is None else f"{int(s // 60)}:{round(s % 60):02d}"


def signed(x):
    return ("+" if x > 0 else "−" if x < 0 else "") + str(abs(round(x)))


def base(chart, h):
    return (
        chart.properties(height=h, background="transparent")
        .configure_view(stroke=None)
        .configure_axis(labelFont=SANS, labelColor=INK3, titleColor=INK3, gridColor=RULE, domainColor=INK3, tickColor=INK3, labelFontSize=12)
    )


x_md = alt.X("d:T", title=None, axis=alt.Axis(format="%-m/%-d", tickCount=7))
last = days.row(-1, named=True)
spike = V["ratio"] > 1.5

top_bar = st.columns([3, 1])
top_bar[0].markdown(f'<h2 style="font:900 21px \'Noto Serif SC\',serif;margin:0">跑步记录</h2>', unsafe_allow_html=True)
top_bar[1].markdown(f'<div class="muted" style="text-align:right">数据截至 {LAST} · 上次打开后新增 {V["newRuns"]} 次跑步</div>', unsafe_allow_html=True)

c1, c2, c3 = st.columns([1.35, 1, 0.95], gap="large")

with c1:
    head = f"负荷突增：ATL 是 CTL 的 {V['ratio']:.1f} 倍" if spike else f"训练负荷{V['tsbWord']}"
    wk = weeks.tail(3)["km"].to_list()
    st.markdown(
        f"""<h1 class="hl">{head}</h1>
<p class="dek">病休一周后直接跑了 {round(wk[1])} km。接下来几天降一点量，让 TSB 回到 −20 以上。</p>
<div class="stat"><div><span class="l">CTL 体能</span><span class="big new" style="color:{FIT}">{round(last['ctl'])}</span></div>
<div><span class="l">ATL 疲劳</span><span class="big new" style="color:{FAT}">{round(last['atl'])}</span></div>
<div><span class="l">TSB 状态</span><span class="big new" style="color:{RED}">{signed(last['tsb'])}</span></div></div>""",
        unsafe_allow_html=True,
    )
    d12 = days.tail(84)
    long = d12.unpivot(index="d", on=["ctl", "atl"], variable_name="k")
    lines = alt.Chart(long).mark_line().encode(
        x=x_md, y=alt.Y("value:Q", title=None, scale=alt.Scale(domain=[0, 100])),
        color=alt.Color("k:N", scale=alt.Scale(domain=["ctl", "atl"], range=[FIT, FAT]), legend=None),
        strokeWidth=alt.condition("datum.k == 'ctl'", alt.value(2.2), alt.value(1.6)),
    )
    layers = [lines]
    if spike:
        on = d12.filter(pl.col("d") == date.fromisoformat(V["onset"]))
        layers += [
            alt.Chart(on).mark_point(shape="circle", size=60, color=RED, filled=False).encode(x="d:T", y="atl:Q"),
            alt.Chart(on).mark_text(align="left", dx=8, dy=-4, color=RED, fontWeight=600, font=SANS).encode(x="d:T", y="atl:Q", text=alt.value(f"{V['onset'][5:7].lstrip('0')} 月 {V['onset'][8:].lstrip('0')} 日起")),
        ]
    st.altair_chart(base(alt.layer(*layers).properties(padding={"right": 90}), 190), use_container_width=True)
    tsb = alt.Chart(d12).mark_bar().encode(
        x=alt.X("d:T", title=None, axis=alt.Axis(format="%-m/%-d", tickCount=7)), y=alt.Y("tsb:Q", title=None, scale=alt.Scale(domain=[-40, 20])),
        color=alt.condition("datum.tsb < 0", alt.value(RED), alt.value(POS)),
    )
    st.altair_chart(base(tsb, 78), use_container_width=True)
    with st.expander("负荷怎么算的"):
        st.markdown("每秒 TRIMP = Δt × HRr × 0.64 × e^(1.92·HRr)。CTL 42 天、ATL 7 天指数加权；TSB = 昨天的 CTL − 昨天的 ATL。")

with c2:
    st.markdown(
        f"""<h2 class="sec">周跑量</h2>
<div class="stat" style="margin-top:10px"><div><span class="l">本周（周一至今）</span><span class="big new">{wk[2]:.1f}</span> km</div>
<div><span class="l">上周</span><span class="big new">{wk[1]:.1f}</span> km</div></div>
<div class="stat"><div><span class="l">滚动 7 天</span><span class="big">{V['roll7']:.1f}</span> km</div></div>""",
        unsafe_allow_html=True,
    )
    w12 = weeks.tail(12).with_columns(cur=pl.col("d") == pl.col("d").max())
    bars = alt.Chart(w12).mark_bar(width=18).encode(
        x=alt.X("d:T", title=None, axis=alt.Axis(format="%-m/%-d", tickCount=6)), y=alt.Y("km:Q", title=None, scale=alt.Scale(domain=[0, 90])),
        color=alt.condition("datum.cur", alt.value(INK3), alt.value(INK)),
    )
    st.altair_chart(base(bars, 200), use_container_width=True)
    st.caption("只算跑的距离，走路不计。本周未完。")

with c3:
    p = D["pred"]
    rows = "".join(
        f'<tr><td>{r["label"]}</td><td class="r"><b>{fmt_dur(r["vdot"])}</b></td><td class="r">{fmt_dur(r["riegel"])}</td><td class="r muted">{fmt_dur(r["garmin"])}</td></tr>'
        for r in p["rows"]
    )
    b = p["basis"]
    cap = (
        f'<p style="color:{RED};font-size:13px"><b>预测已过期。</b>最近一场全力比赛是 {b["date"]} 的{b["name"]}，已超过 6 个月。</p>'
        if p["stale"]
        else f'<p class="muted">依据：{b["date"]} {b["name"]} {fmt_dur(b["time"])}，VDOT {p["V"]:.1f}。Riegel 个人指数 {p["k"]:.3f}。</p>'
    )
    st.markdown(
        f'<h2 class="sec">成绩预测</h2><table class="t" style="margin-top:12px{";opacity:.55" if p["stale"] else ""}"><tr><th>距离</th><th class="r">VDOT</th><th class="r">Riegel</th><th class="r">Garmin</th></tr>{rows}</table>{cap}',
        unsafe_allow_html=True,
    )

st.divider()

h, seg = st.columns([3, 1])
h.markdown('<h2 class="sec" style="border:0">有氧能力：心率 145 时的跑步配速 <span class="muted">越高越快</span></h2>', unsafe_allow_html=True)
rng = seg.segmented_control("时间范围", ["半年", "1 年", "2 年", "全部"], default="2 年", label_visibility="collapsed")
span = {"半年": 183, "1 年": 365, "2 年": 730, "全部": 9999}[rng or "2 年"]
aw = weeks.filter(pl.col("d") >= LAST - timedelta(days=span))
now, ago = V["aerNow"]["aerRoll"], V["aerYearAgo"]["aerRoll"]
st.markdown(f'<p class="dek">最近 4 周 <b class="new" style="position:relative">{fmt_pace(now)} /km</b>，一年前 <b>{fmt_pace(ago)} /km</b>，快了 {round(ago - now)} 秒。</p>', unsafe_allow_html=True)

lo = math.floor(aw["aer"].min() / 10) * 10
hi = math.ceil(aw["aer"].max() / 10) * 10
pace_axis = alt.Axis(values=list(range(lo, hi + 1, 10)), labelExpr="floor(datum.value/60) + ':' + (datum.value%60 < 10 ? '0' : '') + datum.value%60")
y = alt.Y("aer:Q", title=None, scale=alt.Scale(domain=[hi, lo]), axis=pace_axis)
x = alt.X("d:T", title=None, axis=alt.Axis(format="%-m月", tickCount=8))
hover = alt.selection_point(fields=["d"], nearest=True, on="pointerover", empty=False, clear="pointerout")
dots = alt.Chart(aw).mark_circle(size=14, color=DOT).encode(x=x, y=y)
roll = alt.Chart(aw).mark_line(color=INK, strokeWidth=2.4).encode(x=x, y=alt.Y("aerRoll:Q", scale=alt.Scale(domain=[hi, lo]), axis=pace_axis, title=None))
races = pl.DataFrame(D["races"]).with_columns(pl.col("date").str.to_date()).filter(pl.col("date") >= aw["d"].min())
race_rules = alt.Chart(races).mark_rule(strokeDash=[1, 3], color=INK).encode(x="date:T")
# crosshair borrowed from variant C: nearest week, vertical rule, readout text
sel = alt.Chart(aw).mark_rule(color=INK, strokeDash=[2, 3]).encode(x="d:T", opacity=alt.condition(hover, alt.value(1), alt.value(0))).add_params(hover)
read = alt.Chart(aw).transform_filter(hover).transform_calculate(
    t="timeFormat(datum.d, '%Y-%m-%d') + '  ' + floor(datum.aerRoll/60) + ':' + (round(datum.aerRoll%60) < 10 ? '0' : '') + round(datum.aerRoll%60) + ' /km  ' + round(datum.temp) + '°C'"
).mark_text(align="left", dx=6, dy=-10, font=SANS, color=INK, fontWeight=600).encode(x="d:T", y=alt.Y("aerRoll:Q", scale=alt.Scale(domain=[hi, lo])), text="t:N")
last_race = races.tail(1)
note = alt.Chart(last_race).mark_text(align="left", dx=6, dy=-14, color=RED, fontWeight=600, font=SANS).encode(x="date:T", y=alt.value(20), text="name:N")
st.altair_chart(base(alt.layer(race_rules, dots, roll, sel, read, note), 330), use_container_width=True)

temp = alt.Chart(aw).mark_bar(color=TEMP).encode(x=alt.X("d:T", title=None, axis=alt.Axis(format="%-m月", tickCount=8)), y=alt.Y("temp:Q", title=None, scale=alt.Scale(domain=[0, 30])))
st.caption("每周平均温度")
st.altair_chart(base(temp, 70), use_container_width=True)

l1, l2 = st.columns(2, gap="large")
with l1:
    rows = "".join(
        f'<tr><td>{r["d"]}</td><td class="r">{r["km"]:.1f} km</td><td class="r">{fmt_dur(r["min"] * 60)}</td><td class="r">{r["ef"]:.2f}</td><td class="r" style="{"color:" + RED + ";font-weight:600" if r["dec"] > 5 else ""}">{r["dec"]:.1f}%</td></tr>'
        for r in D["longRuns"]
    )
    st.markdown(f'<h2 class="sec">长距离的心率漂移</h2><table class="t"><tr><th>日期</th><th class="r">距离</th><th class="r">时长</th><th class="r">EF</th><th class="r">decoupling</th></tr>{rows}</table>', unsafe_allow_html=True)
with l2:
    st.markdown('<h2 class="sec">最近的比赛</h2>', unsafe_allow_html=True)
    # the native table, for comparison with the hand-written HTML tables
    st.dataframe(
        pl.DataFrame(D["races"]).reverse().select(日期="date", 比赛="name", 成绩=pl.col("time").map_elements(fmt_dur, return_dtype=pl.String)),
        hide_index=True, use_container_width=True,
    )
