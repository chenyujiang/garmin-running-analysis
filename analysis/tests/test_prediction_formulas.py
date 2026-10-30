"""Formula tests for race prediction: VDOT, Riegel, Vickers & Vertosick 2016.

Expected values come from the running-tool formula notes (formulas.md,
sections 2-4): billmill's worked example for VDOT, the Daniels' Running
Formula table (second-hand), and vectors computed from the Vickers 2016
Additional file 1 equations.
"""

import pytest

from running.predict import (
    RIEGEL_K_MAX,
    RIEGEL_K_MIN,
    km_to_miles,
    riegel_exponent,
    riegel_time,
    vdot,
    vdot_time,
    vickers_marathon_exponent,
    vickers_model1,
    vickers_model2,
)

MARATHON_M = 42195.0
HALF_M = 21097.5


def test_vdot_of_a_40_minute_10k_matches_the_billmill_worked_example():
    assert vdot(10000, 40 * 60) == pytest.approx(51.944, abs=0.001)


def test_vdot_of_a_20_minute_5k():
    assert vdot(5000, 20 * 60) == pytest.approx(49.806, abs=0.001)


def hms(h: int, m: int, s: int) -> int:
    return h * 3600 + m * 60 + s


def test_vdot_50_predicts_a_41_20_10k():
    assert vdot_time(50, 10000) == pytest.approx(hms(0, 41, 20), abs=1)


def test_vdot_time_round_trips():
    assert vdot_time(vdot(5000, 1200), 5000) == pytest.approx(1200, abs=0.01)


# Daniels' Running Formula table (second-hand copy, ctyeh.com), within 0.2%.
@pytest.mark.parametrize(
    ("value", "distance_m", "table_s"),
    [
        (40, 5000, hms(0, 24, 8)),
        (40, MARATHON_M, hms(3, 49, 45)),
        (45, 10000, hms(0, 45, 16)),
        (50, HALF_M, hms(1, 31, 35)),
        (55, 10000, hms(0, 38, 6)),
        (60, MARATHON_M, hms(2, 43, 25)),
        (65, HALF_M, hms(1, 12, 53)),
    ],
)
def test_vdot_time_agrees_with_the_daniels_table(value, distance_m, table_s):
    assert vdot_time(value, distance_m) == pytest.approx(table_s, rel=0.002)


@pytest.mark.parametrize(
    ("distance_m", "expected_s"),
    [(10000, hms(0, 41, 42)), (HALF_M, hms(1, 32, 0)), (MARATHON_M, hms(3, 11, 49))],
)
def test_riegel_from_a_20_minute_5k_with_the_default_exponent(distance_m, expected_s):
    assert riegel_time(1200, 5000, distance_m) == pytest.approx(expected_s, abs=1)


def test_riegel_with_a_given_exponent():
    # k fitted from 5K 20:00 + 10K 42:00; 10K -> marathon 3:16:07.
    assert riegel_time(2520, 10000, MARATHON_M, k=1.070389) == pytest.approx(hms(3, 16, 7), abs=1)


def test_personal_exponent_from_two_races():
    k = riegel_exponent([(5000, 1200), (10000, 2520)])
    assert k == pytest.approx(1.070389, abs=1e-6)


def test_personal_exponent_from_three_races_is_the_least_squares_slope():
    k = riegel_exponent([(5000, 1200), (10000, 2520), (HALF_M, 93 * 60)])
    assert k == pytest.approx(1.067444, abs=1e-6)


def test_personal_exponent_needs_two_distinct_distances():
    assert riegel_exponent([(5000, 1200)]) is None
    assert riegel_exponent([(5000, 1200), (5000, 1250)]) is None


def test_vickers_model_1_from_a_1_40_half_at_40_miles_a_week():
    assert vickers_model1(HALF_M, 6000, 40) == pytest.approx(219.769 * 60, abs=0.1)


def test_vickers_model_1_from_a_20_minute_5k_at_30_miles_a_week():
    assert vickers_model1(5000, 1200, 30) == pytest.approx(hms(3, 30, 55), abs=1)


def test_vickers_model_2_marathon_exponent():
    assert vickers_marathon_exponent(1.064777, 40) == pytest.approx(1.141280, abs=1e-5)


def test_vickers_model_2_from_10k_and_half_at_40_miles_a_week():
    t = vickers_model2((10000, 42 * 60), (HALF_M, 93 * 60), 40)
    assert t == pytest.approx(hms(3, 25, 8), abs=1)


def test_vickers_model_2_takes_the_races_in_either_order():
    assert vickers_model2((HALF_M, 93 * 60), (10000, 42 * 60), 40) == pytest.approx(
        hms(3, 25, 8), abs=1
    )


def test_weekly_kilometres_convert_to_miles_as_the_paper_uses():
    assert km_to_miles(64.37376) == pytest.approx(40.0)


def test_personal_exponent_is_clamped_to_a_plausible_range():
    # A slow 5K and a fast 10K would give k < 1.
    assert riegel_exponent([(5000, 1500), (10000, 2700)]) == RIEGEL_K_MIN
    assert riegel_exponent([(5000, 1200), (10000, 3600)]) == RIEGEL_K_MAX
