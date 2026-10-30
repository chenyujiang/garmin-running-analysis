"""Formula-level test: Banister TRIMP against published values.

Vectors from C:/Users/EASON-PC/running-tool-notes/formulas.md §1.1
(sport-activities-features PR #231 corrected values; male a=0.64, b=1.92,
Banister & Calvert 1980 / Morton et al. 1990 via Clin Interv Aging
doi:10.2147/CIA.S211568).
"""

import pytest

from running.load import banister_trimp


def test_54_minutes_at_average_117_bpm_matches_the_published_value():
    assert banister_trimp(minutes=54, hr=117, hr_rest=77, hr_max=173) == pytest.approx(
        32.05, abs=0.005
    )


def test_an_hour_at_hr_max_is_60_times_a_times_e_to_b():
    # 60 · 0.64 · e^1.92; the bug fixed in PR #231 (missing a) gives 409.3.
    assert banister_trimp(minutes=60, hr=173, hr_rest=77, hr_max=173) == pytest.approx(
        261.92, abs=0.005
    )


def test_heart_rate_outside_the_reserve_is_clamped():
    assert banister_trimp(minutes=60, hr=50, hr_rest=55, hr_max=192) == 0
    assert banister_trimp(minutes=60, hr=200, hr_rest=55, hr_max=192) == pytest.approx(
        261.92, abs=0.005
    )
