import numpy as np

from training.flood.metrics import ScoreHistogram, report


def test_scores_match_hand_counts():
    hist = ScoreHistogram()
    hist.add(np.array([0.9, 0.8, 0.2, 0.7, 0.1]), np.array([1, 1, 1, 0, 0]))
    s = hist.scores_at(0.5)  # tp 2, fp 1, fn 1
    assert s["iou"] == 2 / 4
    assert s["f1"] == 4 / 6
    assert s["precision"] == 2 / 3
    assert s["recall"] == 2 / 3


def test_best_threshold_separates_clean_data():
    hist = ScoreHistogram()
    hist.add(np.array([0.9, 0.8, 0.2, 0.1]), np.array([1, 1, 0, 0]))
    t = hist.best_threshold()
    assert 0.2 < t <= 0.8
    assert hist.scores_at(t)["f1"] == 1.0


def test_event_mean_ignores_events_with_nothing_to_score():
    a, b = ScoreHistogram(), ScoreHistogram()
    a.add(np.array([0.9, 0.1]), np.array([1, 0]))
    out = report({"A": a, "B": b}, 0.5)
    assert out["mean_event_iou"] == 1.0
    assert out["events"] == 2
