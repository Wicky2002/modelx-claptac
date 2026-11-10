"""Combine the keyword rules and the transformer, hazard by hazard.

The dataset's labels look rule-made: a hazard is labelled only where its keyword appears, and the event
bit decides which keyword matches count. So for each hazard this tries the keyword alone, the transformer
alone, and the keyword gated by the transformer, and keeps whichever scores best on validation. Sentences
use the transformer. Every choice is made on validation; the test articles only receive it.
"""

from __future__ import annotations

import numpy as np

from training.reports.data import HAZARDS
from training.reports.scores import Outputs, prf

GRID = tuple(round(t, 2) for t in np.arange(0.05, 0.96, 0.05))


def candidates(keyword: np.ndarray, hazard: np.ndarray, event: np.ndarray):
    """(name, threshold, decisions) for one hazard. keyword is 0/1; hazard and event are scores."""
    yield "keyword", None, keyword
    for t in GRID:
        yield "transformer", t, (hazard >= t).astype(np.int64)
        yield "keyword and event", t, keyword & (event >= t)
        yield "keyword and hazard", t, keyword & (hazard >= t)
        yield "keyword or hazard", t, keyword | (hazard >= t)


def apply(rule: str, t, keyword, hazard, event) -> np.ndarray:
    for name, threshold, decisions in candidates(keyword, hazard, event):
        if name == rule and threshold == t:
            return decisions
    raise ValueError(f"unknown rule {rule} at {t}")


def fit(keywords: Outputs, scores: Outputs, truth: Outputs) -> dict:
    """Per hazard, the rule with the best validation F1. Ties keep the simpler, earlier rule."""
    rules = {}
    for i, name in enumerate(HAZARDS, start=1):
        best = None
        for rule, t, decisions in candidates(
            keywords.event[:, i], scores.event[:, i], scores.event[:, 0]
        ):
            f1 = prf(decisions, truth.event[:, i])["f1"]
            if best is None or f1 > best[0]:
                best = (f1, rule, t)
        rules[name] = {"rule": best[1], "threshold": best[2], "val_f1": best[0]}
    return rules


def decide(keywords: Outputs, scores: Outputs, rules: dict, sentence_thresholds: dict) -> Outputs:
    hazards = np.stack(
        [
            apply(
                rules[name]["rule"],
                rules[name]["threshold"],
                keywords.event[:, i],
                scores.event[:, i],
                scores.event[:, 0],
            )
            for i, name in enumerate(HAZARDS, start=1)
        ],
        1,
    )
    # In this dataset an article has an event exactly when it has at least one hazard.
    event = (hazards.sum(1) > 0).astype(np.int64)[:, None]
    return Outputs(
        np.concatenate([event, hazards], 1),
        (scores.location >= sentence_thresholds["location"]).astype(np.int64),
        (scores.impact >= sentence_thresholds["impact"]).astype(np.int64),
    )
