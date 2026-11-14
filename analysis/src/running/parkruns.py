"""Auckland parkrun courses: elevation profile, climbs, even-effort splits and a
pacing strategy per course, for the parkrun page (#/parkruns).

The profiles come from `parkrun_courses.json`, built by
`scripts/build_parkrun_courses.py` from the official course maps and the LINZ
8 m DEM. Nothing here reads the user's data.

Even effort: every metre costs the same metabolic power as the flat target
pace. The cost of a metre comes from Minetti et al. (2002) at the local
grade; downhill only gives back half of Minetti's saving (braking, footing,
turns), and grades are clamped to +-15 %.
"""

import json
from functools import cache
from pathlib import Path
from typing import TypedDict

from running.aerobic import CR_FLAT, minetti_cr

COURSE_M = 5000.0
DEFAULT_TARGET_S = 20 * 60
MAX_GRADE = 0.15
DOWNHILL_SHARE = 0.5
GRADE_SPAN_M = 100.0  # grades and the steepest grade over this distance
CLIMB_MIN_M = 5.0  # climbs and descents smaller than this are not listed
HYSTERESIS_M = 1.0  # a climb ends when the profile drops this far below its top
LEVEL_M = 0.5  # ground within this of a climb's start or end is not part of the climb

DATA_FILE = Path(__file__).with_name("parkrun_courses.json")

# Hand-written from each event's course page (parkrun.co.nz/<slug>/course/).
COURSES: dict[str, dict] = {
    "barrycurtis": {
        "name": "Barry Curtis",
        "area": "Flat Bush",
        "layout": "2.5 km 一圈，跑两圈；草地起步，部分未铺装路",
        "notes": ["每圈经过舞台区后有一段下行到林边，再沿步道回到起点"],
    },
    "cornwallpark": {
        "name": "Cornwall",
        "area": "Cornwall Park",
        "layout": "三圈，路面和草地混合，转弯多",
        "notes": ["每圈有一段下坡到公园入口，随后上 Pohutakawa Drive（树根多，注意脚下）"],
    },
    "hobsonvillepoint": {
        "name": "Hobsonville Point",
        "area": "Hobsonville",
        "layout": "沿海步道一次往返",
        "notes": ["海边路段，风向决定去程和回程哪段更难"],
    },
    "mangerebridge": {
        "name": "Māngere Bridge",
        "area": "Māngere Bridge",
        "layout": "两个方向的往返：东、西、再东，共四个折返",
        "notes": ["海边步道，风是主要变量", "四个折返点，每个提前减速、出弯再加"],
    },
    "millwater": {
        "name": "Millwater",
        "area": "Silverdale",
        "layout": "河口水泥步道一次往返",
        "notes": ["官方描述：前后各三分之一较平，中间三分之一有起伏"],
    },
    "northernpathway": {
        "name": "Northern Pathway",
        "area": "Albany",
        "layout": "过桥下坡道，向东北往返约 1.7 km，再向南往返",
        "notes": ["起终点都要走桥上的无障碍坡道，结尾是一段上坡"],
    },
    "opahekepark": {
        "name": "Ōpaheke Park",
        "area": "Papakura",
        "layout": "宽水泥路三圈，第一圈多一段往返；顺时针",
        "notes": ["高程图按三个整圈近似，没有单独算第一圈的往返段"],
    },
    "orakeibay": {
        "name": "Ōrākei Bay",
        "area": "Ōrākei",
        "layout": "从 Ōrākei Basin 栈道出发，水泥共享步道向东 2.5 km 后折返",
        "notes": ["起点在栈道上；DEM 看不到栈道和桥本身，这几段的高程可能失真"],
    },
    "owairaka": {
        "name": "Owairaka",
        "area": "Mt Albert",
        "layout": "两个方向的往返：先向西过高速桥，再向东",
        "notes": ["有地下通道和跨高速的 Te Whitinga 桥，DEM 在桥上可能失真"],
    },
    "parrspark": {
        "name": "Parrs Park",
        "area": "Glen Eden",
        "layout": "2.5 km 往返跑两次，草地和林间小路",
        "notes": [
            "硬土为主，多处浮土，雨后或冬天建议越野鞋",
            "有木栈道和小桥，路窄，超人看准宽处",
            "穿过可放狗区，路上可能有狗",
        ],
    },
    "sherwoodreserve": {
        "name": "Sherwood Reserve",
        "area": "Forrest Hill",
        "layout": "三圈，每圈过两座桥、穿过草地，并有一段往返",
        "notes": ["栈道下穿 Glencoe Road，个子高要低头", "全程靠左"],
    },
    "southernpath": {
        "name": "Southern Path",
        "area": "Takanini",
        "layout": "铺装共享步道，两段往返：先向北，再向南",
        "notes": ["没有厕所", "三个折返点，提前减速、出弯再加"],
    },
    "sunnynook": {
        "name": "Sunnynook",
        "area": "Sunnynook",
        "layout": "顺时针三个大圈加两个小圈",
        "notes": ["高程图按大圈近似；小圈少了公园北端那段", "多圈路线，全程靠左"],
    },
    "tuffcraterreserve": {
        "name": "Tuff Crater Reserve",
        "area": "Northcote",
        "layout": "沿火山口边缘的越野往返，压实碎石和木栈道",
        "notes": ["路窄，超人看准宽处", "DEM 看不到木栈道本身，栈道附近的高程可能失真"],
    },
    "warkworthshowgrounds": {
        "name": "Warkworth Showgrounds",
        "area": "Warkworth",
        "layout": "小圈三次加长往返两次，碎石路为主",
        "notes": ["高程图按两次长往返近似，没有单独算小圈", "有一座短木桥，终点在草地上"],
    },
    "westernsprings": {
        "name": "Western Springs",
        "area": "Western Springs",
        "layout": "顺时针绕湖三圈",
        "notes": [],
    },
}

TAGS = (  # (gain up to, tag); the steepest 100 m can move a course up one tag
    (15.0, "平路"),
    (30.0, "微起伏"),
    (50.0, "起伏"),
    (float("inf"), "多坡"),
)


class Split(TypedDict):
    km: int
    time_s: float
    pace_s_per_km: float
    net_m: float  # elevation change over the km


class Climb(TypedDict):
    kind: str  # "up" or "down"
    start_m: float
    end_m: float
    change_m: float
    grade: float  # mean, signed


class Course(TypedDict):
    slug: str
    name: str
    area: str
    url: str
    layout: str
    notes: list[str]
    fit_note: str | None
    tag: str
    gain_m: float
    loss_m: float
    range_m: float
    max_grade: float
    estimate_s: float
    delta_s: float
    splits: list[Split]
    climbs: list[Climb]
    strategy: list[str]
    step_m: float
    elevation_m: list[float]


class Method(TypedDict):
    description: str


class ParkrunCourses(TypedDict):
    target_s: float
    source: str
    method: Method
    courses: list[Course]


@cache
def _data() -> dict:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def effort_cost(grade: float) -> float:
    """Metabolic cost per metre (J/kg/m) at `grade`, as this page paces it."""
    g = max(-MAX_GRADE, min(MAX_GRADE, grade))
    cr = minetti_cr(g)
    return cr if cr >= CR_FLAT else CR_FLAT + (cr - CR_FLAT) * DOWNHILL_SHARE


def segment_times(ele: list[float], step: float, target_s: float) -> list[float]:
    """Seconds for each step at the power that runs a flat 5 km in `target_s`."""
    flat_s_per_m = target_s / COURSE_M
    return [
        step * flat_s_per_m * effort_cost((b - a) / step) / CR_FLAT
        for a, b in zip(ele, ele[1:], strict=False)
    ]


def splits(ele: list[float], step: float, target_s: float) -> list[Split]:
    times = segment_times(ele, step, target_s)
    per_km = round(1000 / step)
    out: list[Split] = []
    for k in range(0, len(times), per_km):
        t = sum(times[k : k + per_km])
        km_m = min(per_km, len(times) - k) * step
        out.append(
            {
                "km": k // per_km + 1,
                "time_s": round(t, 1),
                "pace_s_per_km": round(t * 1000 / km_m, 1),
                "net_m": round(ele[min(k + per_km, len(ele) - 1)] - ele[k], 1),
            }
        )
    return out


def climbs(ele: list[float], step: float) -> list[Climb]:
    """Runs of rising or falling ground of at least CLIMB_MIN_M, with hysteresis."""
    out: list[Climb] = []
    lo = hi = 0  # indices of the running minimum and maximum since the last turn
    direction = 0
    start = 0
    for i, v in enumerate(ele):
        if direction >= 0 and v > ele[hi]:
            hi = i
        if direction <= 0 and v < ele[lo]:
            lo = i
        if direction == 0:
            if ele[hi] - ele[lo] >= HYSTERESIS_M:
                direction = 1 if hi > lo else -1
                start = lo if direction == 1 else hi
        elif direction == 1 and ele[hi] - v >= HYSTERESIS_M:
            out.append(_climb(ele, step, start, hi))
            direction, start, lo = -1, hi, i
        elif direction == -1 and v - ele[lo] >= HYSTERESIS_M:
            out.append(_climb(ele, step, start, lo))
            direction, start, hi = 1, lo, i
    if direction:
        out.append(_climb(ele, step, start, hi if direction == 1 else lo))
    return [c for c in out if abs(c["change_m"]) >= CLIMB_MIN_M]


def _climb(ele: list[float], step: float, a: int, b: int) -> Climb:
    """The run from index a to b, from the last point still level with its start
    to the first point level with its end (within LEVEL_M)."""
    sign = 1 if ele[b] >= ele[a] else -1
    first, last = ele[a], ele[b]
    a = max(i for i in range(a, b + 1) if (ele[i] - first) * sign <= LEVEL_M)
    b = min(i for i in range(a, b + 1) if (last - ele[i]) * sign <= LEVEL_M)
    change = ele[b] - ele[a]
    length = max(step, (b - a) * step)
    return {
        "kind": "up" if change > 0 else "down",
        "start_m": a * step,
        "end_m": b * step,
        "change_m": round(change, 1),
        "grade": round(change / length, 4),
    }


def max_grade(ele: list[float], step: float) -> float:
    n = max(1, round(GRADE_SPAN_M / step))
    return max((abs(ele[i + n] - ele[i]) / (n * step) for i in range(len(ele) - n)), default=0.0)


def tag(gain: float, steepest: float) -> str:
    i = next(i for i, (limit, _) in enumerate(TAGS) if gain <= limit)
    if steepest >= 0.08:
        i = min(i + 1, len(TAGS) - 1)
    return TAGS[i][1]


def _km(m: float) -> str:
    return f"{m / 1000:.1f}"


def _pace(s: float) -> str:
    t = round(s)
    return f"{t // 60}:{t % 60:02d}"


def strategy(c: dict, target_s: float) -> list[str]:
    """Pacing advice in Chinese from the numbers of one course."""
    out: list[str] = []
    flat = target_s / 5
    sp: list[Split] = c["splits"]
    t = c["tag"]
    if t == "平路":
        out.append(f"平路，按目标配速 {_pace(flat)}/km 匀速跑，前 1 km 不要快于目标 5 秒以上。")
    elif t == "微起伏":
        out.append("小起伏，按体感匀速：上坡少掉几秒、下坡顺势收回，不必每公里卡同一配速。")
    else:
        out.append(
            "坡多，按用力而不是配速跑：上坡配速掉下来是正常的，盯住呼吸和步频，坡顶后再提速。"
        )
    first, last = sp[0], sp[-1]
    if first["net_m"] <= -3:
        out.append(
            f"开头 1 km 下降 {-first['net_m']:.0f} m，容易跑太快；"
            f"按 {_pace(first['pace_s_per_km'])}/km 左右控制，别透支。"
        )
    elif first["net_m"] >= 3:
        out.append(
            f"开头 1 km 上升 {first['net_m']:.0f} m，"
            f"这一公里慢到 {_pace(first['pace_s_per_km'])}/km 也不亏，后面会还回来。"
        )
    if last["net_m"] >= 3:
        out.append(
            f"最后 1 km 上升 {last['net_m']:.0f} m：第 4 km 留一点力，坡上保持用力，"
            "最后 200 m 再冲刺。"
        )
    elif last["net_m"] <= -3:
        out.append(f"最后 1 km 下降 {-last['net_m']:.0f} m，可以早一点开始加速。")
    ups = sorted((x for x in c["climbs"] if x["kind"] == "up"), key=lambda x: -x["change_m"])
    for x in ups[:2]:
        out.append(
            f"{_km(x['start_m'])}–{_km(x['end_m'])} km 爬 {x['change_m']:.0f} m"
            f"（平均 {x['grade'] * 100:.1f}%）：缩小步幅、提高步频，保持用力不变。"
        )
    if c["max_grade"] >= 0.06:
        out.append(
            f"最陡的 100 m 约 {c['max_grade'] * 100:.0f}%，"
            "短陡坡别硬顶配速，过了坡顶 50 m 再回到节奏。"
        )
    downs = [x for x in c["climbs"] if x["kind"] == "down" and x["change_m"] <= -6]
    if downs:
        out.append("下坡放松让腿转起来，身体略前倾，不要刹车，这里能收回上坡丢的时间。")
    delta = c["delta_s"]
    if abs(delta) >= 3:
        out.append(
            f"同样用力，这条路线比平路 5 km 慢约 {delta:.0f} 秒，"
            f"目标 {_pace(target_s)} 对应这里约 {_pace(c['estimate_s'])}。"
        )
    return out


def course(slug: str, target_s: float = DEFAULT_TARGET_S) -> Course:
    raw = _data()["courses"][slug]
    meta = COURSES[slug]
    step = float(_data()["step_m"])
    ele = [float(v) for v in raw["elevation_m"]]
    diffs = [b - a for a, b in zip(ele, ele[1:], strict=False)]
    gain = sum(d for d in diffs if d > 0)
    loss = -sum(d for d in diffs if d < 0)
    steepest = max_grade(ele, step)
    sp = splits(ele, step, target_s)
    estimate = sum(s["time_s"] for s in sp)
    c = {
        "slug": slug,
        "name": meta["name"],
        "area": meta["area"],
        "url": f"https://www.parkrun.co.nz/{slug}/course/",
        "layout": meta["layout"],
        "notes": list(meta["notes"]),
        "fit_note": raw.get("fit_note"),
        "tag": tag(gain, steepest),
        "gain_m": round(gain, 1),
        "loss_m": round(loss, 1),
        "range_m": round(max(ele) - min(ele), 1),
        "max_grade": round(steepest, 4),
        "estimate_s": round(estimate, 1),
        "delta_s": round(estimate - target_s, 1),
        "splits": sp,
        "climbs": climbs(ele, step),
        "step_m": step,
        "elevation_m": ele,
    }
    c["strategy"] = strategy(c, target_s)
    return c  # type: ignore[return-value]


METHOD = (
    "路线取自各 parkrun 官方路线页的地图，按官方描述排成实际跑法（几圈、往返），"
    "缩放到 5 km；高程取 LINZ 8 m 地形 DEM（OpenTopoData nzdem8m），每 10 m 一点，"
    "用 120 m 闭运算填掉桥和栈道下的假凹陷，再做 60 m 平滑。DEM 是地面高程，"
    "和手表气压高度对比形状吻合（平均差 1–3 m），但累计爬升偏小：手表的累计爬升通常"
    "高出约一倍，其中一部分是气压噪声。分段配速按均匀用力：每米的能耗取 Minetti (2002) "
    "在该坡度的跑步能耗，下坡只算一半的省力，坡度截在 ±15%，再按平路 5 km 目标时间的"
    "功率折算成时间。不计转弯、折返、路面、风和人群。"
)


def parkrun_courses(target_s: float = DEFAULT_TARGET_S) -> ParkrunCourses:
    slugs = [s for s in COURSES if s in _data()["courses"]]
    courses = sorted((course(s, target_s) for s in slugs), key=lambda c: c["gain_m"])
    return {
        "target_s": target_s,
        "source": _data()["source"],
        "method": {"description": METHOD},
        "courses": courses,
    }
