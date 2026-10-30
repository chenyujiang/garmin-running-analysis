"""Race prediction formulas: Daniels/Gilbert VDOT, Riegel, Vickers & Vertosick 2016.

Sources are checked in the running-tool formula notes (formulas.md, sections 2-4).
"""

import math


def _vo2(v_m_per_min: float) -> float:
    return -4.60 + 0.182258 * v_m_per_min + 0.000104 * v_m_per_min**2


def _pct_max(t_min: float) -> float:
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t_min) + 0.2989558 * math.exp(-0.1932605 * t_min)


def vdot(distance_m: float, time_s: float) -> float:
    """Daniels & Gilbert (Oxygen Power, 1979): VO2 at race speed / %VO2max sustainable."""
    t_min = time_s / 60.0
    return _vo2(distance_m / t_min) / _pct_max(t_min)


def vdot_time(value: float, distance_m: float) -> float:
    """Race time (s) at `distance_m` for a given VDOT: solve vdot(d, t) = value by
    bisection. vdot(d, t) falls monotonically with t over the useful range."""
    lo, hi = 60.0, 60_000.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if vdot(distance_m, mid) > value:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


RIEGEL_K = 1.06
# Not from Riegel: a guard against two near distances or a soft race giving a
# nonsensical personal exponent.
RIEGEL_K_MIN = 1.01
RIEGEL_K_MAX = 1.20


def riegel_time(time_s: float, distance_m: float, target_m: float, k: float = RIEGEL_K) -> float:
    """Riegel (1977/1981): T2 = T1 x (D2 / D1)^k."""
    return time_s * (target_m / distance_m) ** k


def riegel_exponent(races: list[tuple[float, float]]) -> float | None:
    """Personal Riegel exponent from (distance_m, time_s) pairs: least-squares
    slope of ln T on ln D (for two races, ln(T2/T1) / ln(D2/D1)), clamped to
    [RIEGEL_K_MIN, RIEGEL_K_MAX]. None without two distinct distances."""
    if len({d for d, _ in races}) < 2:
        return None
    xs = [math.log(d) for d, _ in races]
    ys = [math.log(t) for _, t in races]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    k = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sum(
        (x - mx) ** 2 for x in xs
    )
    return min(max(k, RIEGEL_K_MIN), RIEGEL_K_MAX)


# Vickers AJ, Vertosick EA. BMC Sports Sci Med Rehabil 2016;8:26 (PMC5000509),
# Additional file 1. Distances in metres, times in seconds, speeds in m/s,
# "typical mileage" in miles per week (entered as mileage / 10).
MARATHON_M = 42195.0
MILE_KM = 1.609344
VICKERS_RIEGEL_K = 1.07
VICKERS_M1 = (0.16018617, 0.83076202, 0.06423826)  # intercept, v_Riegel, mileage/10
VICKERS_M2 = (1.4510756, -0.23797948, -0.01410023)  # intercept, k_r2r1, mileage/10


def km_to_miles(km: float) -> float:
    return km / MILE_KM


def vickers_model1(distance_m: float, time_s: float, weekly_miles: float) -> float:
    """Model 1 (one non-marathon race): Riegel k=1.07 speed corrected by mileage.
    Returns the marathon time in seconds."""
    v_riegel = MARATHON_M / riegel_time(time_s, distance_m, MARATHON_M, VICKERS_RIEGEL_K)
    a, b, c = VICKERS_M1
    v = a + b * v_riegel + c * weekly_miles / 10
    return MARATHON_M / v


def vickers_marathon_exponent(k_r2r1: float, weekly_miles: float) -> float:
    """Model 2: the marathon exponent from the two races' own exponent and mileage."""
    a, b, c = VICKERS_M2
    return a + b * k_r2r1 + c * weekly_miles / 10


def vickers_model2(
    race_a: tuple[float, float], race_b: tuple[float, float], weekly_miles: float
) -> float:
    """Model 2 (two non-marathon races, (distance_m, time_s)): Riegel from the
    longer race with the Vickers-corrected exponent. Marathon time in seconds."""
    (d1, t1), (d2, t2) = sorted([race_a, race_b])
    k_r2r1 = math.log(t2 / t1) / math.log(d2 / d1)
    return riegel_time(t2, d2, MARATHON_M, vickers_marathon_exponent(k_r2r1, weekly_miles))
