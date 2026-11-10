import numpy as np

from training.flood.water import NO_DATA, tile_names, water_channel


def test_tile_is_named_by_its_north_west_corner():
    assert tile_names(12.0, 41.0, 13.0, 42.0) == ["10E_50N"]
    assert tile_names(-80.7, -6.4, -80.5, -6.3) == ["90W_0N"]


def test_box_across_a_tile_edge_needs_both_tiles():
    assert tile_names(9.5, 41.0, 10.5, 42.0) == ["0E_50N", "10E_50N"]
    assert tile_names(12.0, 39.5, 13.0, 40.5) == ["10E_40N", "10E_50N"]


def test_only_mostly_water_pixels_count_and_no_data_is_not_water():
    occurrence = np.array([0, 49, 50, 100, NO_DATA], dtype=np.uint8)
    assert water_channel(occurrence).tolist() == [0.0, 0.0, 1.0, 1.0, 0.0]
