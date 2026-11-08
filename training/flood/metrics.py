"""Flood-class scores from a histogram of pixel scores.

A histogram gives exact counts at every threshold without keeping billions of pixels in memory, so the
operating threshold can be chosen on validation data and then applied once to the test events.
"""

from __future__ import annotations

import numpy as np

BINS = 1000


class ScoreHistogram:
    def __init__(self) -> None:
        self.pos = np.zeros(BINS, dtype=np.int64)
        self.neg = np.zeros(BINS, dtype=np.int64)

    def add(self, scores: np.ndarray, labels: np.ndarray) -> None:
        """Add pixels. ``scores`` are in [0, 1]; ``labels`` are 0 or 1 with invalid pixels removed."""
        idx = np.clip((scores * BINS).astype(np.int64), 0, BINS - 1)
        self.pos += np.bincount(idx[labels == 1], minlength=BINS)
        self.neg += np.bincount(idx[labels == 0], minlength=BINS)

    def merge(self, other: "ScoreHistogram") -> None:
        self.pos += other.pos
        self.neg += other.neg

    def scores_at(self, threshold: float) -> dict[str, float]:
        """Scores when every pixel in a bin at or above ``threshold`` is called flood."""
        cut = int(round(threshold * BINS))
        tp = int(self.pos[cut:].sum())
        fp = int(self.neg[cut:].sum())
        fn = int(self.pos[:cut].sum())
        return {
            "threshold": threshold,
            "iou": tp / (tp + fp + fn) if tp + fp + fn else float("nan"),
            "f1": 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else float("nan"),
            "precision": tp / (tp + fp) if tp + fp else float("nan"),
            "recall": tp / (tp + fn) if tp + fn else float("nan"),
        }

    def best_threshold(self) -> float:
        """The threshold with the highest F1. Call this on validation data only."""
        tp = np.cumsum(self.pos[::-1])[::-1]
        fp = np.cumsum(self.neg[::-1])[::-1]
        fn = self.pos.sum() - tp
        denom = 2 * tp + fp + fn
        f1 = np.divide(2 * tp, denom, out=np.zeros(BINS), where=denom > 0)
        return int(f1.argmax()) / BINS


def report(by_event: dict[str, ScoreHistogram], threshold: float) -> dict:
    """Scores over all pixels, plus the mean across events so large events cannot hide small ones."""
    total = ScoreHistogram()
    per_event = {}
    for event, hist in sorted(by_event.items()):
        total.merge(hist)
        per_event[event] = hist.scores_at(threshold)
    ious = [e["iou"] for e in per_event.values() if e["iou"] == e["iou"]]
    f1s = [e["f1"] for e in per_event.values() if e["f1"] == e["f1"]]
    return {
        "all_pixels": total.scores_at(threshold),
        "mean_event_iou": float(np.mean(ious)) if ious else float("nan"),
        "mean_event_f1": float(np.mean(f1s)) if f1s else float("nan"),
        "events": len(per_event),
        "per_event": per_event,
    }
