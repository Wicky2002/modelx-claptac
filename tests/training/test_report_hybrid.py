import numpy as np

from training.reports import hybrid
from training.reports.data import HAZARDS
from training.reports.scores import Outputs


def _outputs(event):
    return Outputs(np.array(event), np.array([0.9, 0.1]), np.array([0.2, 0.8]))


def test_fit_picks_the_gated_keyword_when_the_event_bit_decides():
    n = len(HAZARDS) + 1
    # Article 0 mentions a flood and has an event; article 1 mentions one without an event.
    keywords = _outputs([[1] + [0] * (n - 1), [1] + [0] * (n - 1)])
    keywords.event[:, 2] = [1, 1]
    scores = _outputs(np.zeros((2, n)))
    scores.event[:, 0] = [0.9, 0.1]
    truth = _outputs(np.zeros((2, n), dtype=np.int64))
    truth.event[0, 0] = truth.event[0, 2] = 1
    rules = hybrid.fit(keywords, scores, truth)
    assert rules["flood"]["rule"] == "keyword and event"
    assert rules["flood"]["val_f1"] == 1.0
    out = hybrid.decide(keywords, scores, rules, {"location": 0.5, "impact": 0.5})
    assert out.event[:, 2].tolist() == [1, 0]
    assert out.event[:, 0].tolist() == [1, 0]  # event exactly when some hazard is found
    assert out.location.tolist() == [1, 0] and out.impact.tolist() == [0, 1]
