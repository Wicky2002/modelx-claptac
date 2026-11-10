import numpy as np
import pandas as pd

from training.sensors.forecast import features, scores, split


def frame(n=40):
    index = pd.date_range("2022-12-01 01:00", periods=n, freq="h")
    return pd.DataFrame({"a": np.arange(n, dtype=float), "b": np.ones(n)}, index=index)


def test_features_never_look_ahead_and_target_is_shifted():
    x, y, now = features(frame(), "a", 3)
    assert (y - now == 3).all()
    assert (x["a t-0"] == now).all()
    assert (x["a t-5"] == now - 5).all()


def test_splits_are_by_time_and_do_not_overlap():
    f = frame(30)
    s = {
        "splits": {
            "train": {"first": "2022-12-01 01:00", "last": "2022-12-01 20:00"},
            "test": {"first": "2022-12-01 21:00", "last": "2022-12-02 06:00"},
        }
    }
    parts = split(f, s)
    assert parts["train"].index.max() < parts["test"].index.min()
    assert len(parts["train"]) + len(parts["test"]) == 30


def test_scores():
    assert scores(np.array([0.0, 0.0]), np.array([1.0, -3.0])) == {"mae": 2.0, "rmse": 2.2361}
