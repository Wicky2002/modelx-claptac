"""Scores for the report models. Macro-F1 covers the eight hazards; the rest are reported apart."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from training.reports.data import HAZARDS, LABELS


def prf(pred: np.ndarray, true: np.ndarray) -> dict[str, float]:
    tp = int(((pred == 1) & (true == 1)).sum())
    fp = int(((pred == 1) & (true == 0)).sum())
    fn = int(((pred == 0) & (true == 1)).sum())
    return {
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "f1": 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 0.0,
        "support": tp + fn,
    }


@dataclass
class Outputs:
    """Scores or 0/1 decisions, for one split."""

    event: np.ndarray  # articles x 9
    location: np.ndarray  # one value per kept sentence, over all articles
    impact: np.ndarray


def best_threshold(score: np.ndarray, true: np.ndarray) -> float:
    grid = np.arange(0.05, 0.96, 0.05)
    return float(grid[int(np.argmax([prf(score >= t, true)["f1"] for t in grid]))])


def fit_thresholds(scores: Outputs, truth: Outputs) -> dict:
    """Choose every threshold on validation data."""
    return {
        "event": [best_threshold(scores.event[:, i], truth.event[:, i]) for i in range(len(LABELS))],
        "location": best_threshold(scores.location, truth.location),
        "impact": best_threshold(scores.impact, truth.impact),
    }


def decide(scores: Outputs, thresholds: dict) -> Outputs:
    return Outputs(
        (scores.event >= np.array(thresholds["event"])).astype(np.int64),
        (scores.location >= thresholds["location"]).astype(np.int64),
        (scores.impact >= thresholds["impact"]).astype(np.int64),
    )


def report(pred: Outputs, truth: Outputs) -> dict:
    per_label = {name: prf(pred.event[:, i], truth.event[:, i]) for i, name in enumerate(LABELS)}
    return {
        "macro_f1_hazards": float(np.mean([per_label[h]["f1"] for h in HAZARDS])),
        "per_label": per_label,
        "location_sentences": prf(pred.location, truth.location),
        "impact_sentences": prf(pred.impact, truth.impact),
    }
