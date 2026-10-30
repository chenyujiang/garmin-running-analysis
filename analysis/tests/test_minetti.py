"""Formula-level tests: Minetti et al. 2002 energy cost of running, Cr(i), and the
grade-adjusted speed derived from it.

Sources: J Appl Physiol 2002;93:1039-1046, Fig. 1 legend (polynomial) and
Table 2 (measured Cr). Polynomial values and GAP vectors were computed by hand
from the published coefficients (see the shared notes, formulas.md section 5).
"""

import pytest

from running.aerobic import gap_speed, minetti_cr

# Table 2: measured energy cost of running, J/kg/m, by gradient (rise/run).
MEASURED = {
    -0.45: 3.92,
    -0.40: 3.49,
    -0.35: 2.81,
    -0.30: 2.43,
    -0.20: 1.73,
    -0.10: 1.93,
    0.0: 3.40,
    0.10: 5.77,
    0.20: 8.92,
    0.30: 12.52,
    0.35: 14.43,
    0.40: 16.83,
    0.45: 18.93,
}


@pytest.mark.parametrize(
    ("grade", "expected"),
    [
        (0.0, 3.6),
        (0.05, 4.6852),
        (0.10, 5.9682),
        (0.15, 7.4170),
        (0.45, 19.4260),
        (-0.10, 2.1517),
        (-0.20, 1.8000),
        (-0.45, 4.0323),
    ],
)
def test_cr_polynomial_matches_the_published_coefficients(grade, expected):
    assert minetti_cr(grade) == pytest.approx(expected, abs=1e-4)


@pytest.mark.parametrize(("grade", "measured"), sorted(MEASURED.items()))
def test_cr_polynomial_stays_close_to_the_measured_table(grade, measured):
    # The fit has R^2 = 0.999; the largest gap to Table 2 is 0.5 J/kg/m at +45 %.
    assert minetti_cr(grade) == pytest.approx(measured, abs=0.55)


@pytest.mark.parametrize(
    ("grade", "expected"),
    [(0.0, 3.0), (0.05, 3.9043), (0.10, 4.9735), (-0.05, 2.2883), (-0.10, 1.7931)],
)
def test_gap_speed_at_three_metres_per_second(grade, expected):
    assert gap_speed(3.0, grade) == pytest.approx(expected, abs=1e-4)
