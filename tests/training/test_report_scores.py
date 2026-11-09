import numpy as np
import pytest

from training.reports import evaluate, keywords
from training.reports.data import HAZARDS, Article
from training.reports.scores import Outputs, best_threshold, decide, prf, report


def article(*sentences):
    n = len(sentences)
    return Article(0, list(sentences), np.zeros(9, np.int64), np.zeros(n, np.int64), np.zeros(n, np.int64))


def test_precision_recall_f1_by_hand():
    s = prf(np.array([1, 1, 0, 0]), np.array([1, 0, 1, 0]))
    assert (s["precision"], s["recall"], s["f1"], s["support"]) == (0.5, 0.5, 0.5, 2)


def test_threshold_is_chosen_from_scores():
    assert best_threshold(np.array([0.1, 0.2, 0.8, 0.9]), np.array([0, 0, 1, 1])) > 0.2


def test_macro_f1_covers_the_hazards_only():
    n = len(HAZARDS) + 1
    gold = Outputs(np.ones((2, n), np.int64), np.array([1, 0]), np.array([0, 1]))
    pred = Outputs(gold.event.copy(), gold.location, gold.impact)
    pred.event[:, 0] = 0  # event-present is wrong, every hazard is right
    assert report(pred, gold)["macro_f1_hazards"] == 1.0


def test_decide_uses_each_threshold():
    scores = Outputs(np.full((1, 9), 0.5), np.array([0.5]), np.array([0.5]))
    t = {"event": [0.4] * 8 + [0.6], "location": 0.4, "impact": 0.6}
    out = decide(scores, t)
    assert out.event.tolist() == [[1, 1, 1, 1, 1, 1, 1, 1, 0]]
    assert (out.location[0], out.impact[0]) == (1, 0)


def test_keyword_rules_find_hazards_places_and_impact():
    out = keywords.predict(
        [article("A flood hit the town.", "Three people were killed in Kandy."), article("The match ended.")]
    )
    flood = HAZARDS.index("flood") + 1
    assert out.event[0, flood] == 1 and out.event[0, 0] == 1
    assert out.event[1].sum() == 0
    assert out.location.tolist() == [0, 1, 0]
    assert out.impact.tolist() == [0, 1, 0]


def test_test_split_cannot_be_scored_twice_or_without_the_transformer(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    common = ["evaluate", "--data", str(tmp_path), "--run", str(run), "--split", "test"]
    monkeypatch.setattr("sys.argv", [*common, "--baseline-only"])
    with pytest.raises(SystemExit):
        evaluate.main()
    (run / "report_test.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("sys.argv", common)
    with pytest.raises(SystemExit):
        evaluate.main()
    assert (run / "report_test.json").read_text(encoding="utf-8") == "{}"
