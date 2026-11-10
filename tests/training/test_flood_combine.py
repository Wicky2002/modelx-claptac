import numpy as np
import pytest

from training.flood.combine import SMOOTHING, dihedral, options, smooth, undo_dihedral


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


def test_options_cover_every_subset():
    rows = options(["a", "b", "c"])
    assert len(rows) == 7 * 2 * len(SMOOTHING)
    assert {"members": ["a"], "tta": False, "smooth": 1} in rows
