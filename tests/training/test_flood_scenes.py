import numpy as np

from training.flood.data import IGNORE
from training.flood.scenes import channels, flood_layer, new_water_km2
from training.flood.water import NO_DATA


def test_channels_match_the_training_layout_without_hydrography():
    vv = np.array([[1.0, 0.01]], dtype=np.float32)
    vh = np.array([[0.1, 0.001]], dtype=np.float32)
    dem = np.array([[100.0, 300.0]], dtype=np.float32)
    occurrence = np.array([[80, NO_DATA]], dtype=np.uint8)
    x, valid = channels(vv, vh, dem, occurrence)
    assert x.shape == (6, 1, 2)
    assert x[0].tolist() == [[0.0, -20.0]]
    assert x[1].tolist() == [[-10.0, -30.0]]
    assert x[2].tolist() == [[-1.0, 1.0]]
    assert x[3].sum() == 0 and x[4].sum() == 0
    assert x[5].tolist() == [[1.0, 0.0]]
    assert valid.all()


def test_missing_radar_or_elevation_is_not_valid():
    vv = np.array([[np.nan, 1.0, 0.0, 1.0]], dtype=np.float32)
    vh = np.array([[1.0, 1.0, 0.0, 1.0]], dtype=np.float32)
    dem = np.array([[1.0, np.nan, 1.0, 1.0]], dtype=np.float32)
    _, valid = channels(vv, vh, dem, np.zeros((1, 4), dtype=np.uint8))
    assert valid.tolist() == [[False, False, False, True]]


def test_layer_marks_no_data_and_area_leaves_out_permanent_water():
    probability = np.array([[0.9, 0.9, 0.1, 0.9]])
    valid = np.array([[True, True, True, False]])
    layer = flood_layer(probability, 0.5, valid)
    assert layer.tolist() == [[1, 1, 0, IGNORE]]
    permanent = np.array([[0.0, 1.0, 0.0, 0.0]])
    assert new_water_km2(layer, permanent, 100.0) == 100.0 / 1e6
