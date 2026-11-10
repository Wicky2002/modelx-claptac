import numpy as np
import pytest

from training.flood.combine import (
    SLOPES,
    SMOOTHING,
    calibrate,
    dihedral,
    expected_calibration_error,
    finish,
    first_stage,
    fit_temperature,
    second_stage,
    slope_degrees,
    smooth,
    undo_dihedral,
)


def test_each_flip_and_rotation_undoes_exactly():
    x = np.arange(2 * 3 * 4, dtype=np.float32).reshape(2, 3, 4)
    seen = set()
    for k in range(8):
        assert np.array_equal(undo_dihedral(dihedral(x, k), k), x)
        seen.add(np.ascontiguousarray(dihedral(x[0], k)).tobytes() + bytes(dihedral(x[0], k).shape))
    assert len(seen) == 8


def test_smoothing_is_a_local_mean_and_removes_a_speck():
    p = np.zeros((7, 7), dtype=np.float32)
    p[3, 3] = 0.9
    s = smooth(p, 3)
    assert s.shape == p.shape
    assert s[3, 3] == pytest.approx(0.1)
    assert s.max() < 0.5
    assert np.array_equal(smooth(p, 1), p)
    assert np.allclose(smooth(np.full((5, 6), 0.4, dtype=np.float32), 5), 0.4)


def test_slope_of_a_ramp_and_the_steep_cutoff():
    # Relative elevation is in hundreds of metres; a 10 m rise per 10 m pixel is 45 degrees.
    ramp = np.tile(np.arange(6, dtype=np.float32) * 0.1, (4, 1))
    assert np.allclose(slope_degrees(ramp), 45.0, atol=1e-3)
    assert np.allclose(slope_degrees(np.zeros((4, 4))), 0.0)
    p = np.full((4, 6), 0.8, dtype=np.float32)
    assert finish([p], 1, slope_degrees(ramp), 30.0).max() == 0.0
    assert np.allclose(finish([p], 1, slope_degrees(ramp), None), 0.8)
    assert np.allclose(finish([p, p * 0], 1, None, None), 0.4)


def test_temperature_fixes_overconfident_probabilities():
    rng = np.random.default_rng(0)
    truth_p = rng.uniform(0.05, 0.95, 20000)
    y = (rng.uniform(size=truth_p.size) < truth_p).astype(np.float64)
    overconfident = calibrate(truth_p, 0.4)  # pushed towards 0 and 1
    t = fit_temperature(overconfident, y)
    assert t == pytest.approx(1 / 0.4, rel=0.15)
    before = expected_calibration_error(overconfident, y)
    after = expected_calibration_error(calibrate(overconfident, t), y)
    assert after < before / 2


def test_stages_keep_the_choices_few():
    first = first_stage(["a", "b", "c"])
    assert len(first) == 7 * 2
    second = second_stage(first[0])
    assert len(second) == len(SMOOTHING) * len(SLOPES)
    assert all(o["members"] == first[0]["members"] for o in second)
