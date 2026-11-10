"""What the agents ask of each model, and how they read the answer.

A wrapper around a trained model has to accept these features and return these outputs. Anything
else reads as "the model said nothing", so the agent keeps its rules.
"""

from __future__ import annotations

import math

from atlas.learning.inference import Prediction
from atlas.learning.registry import FeatureSpec

# A2: output {"edges": {edge_id: fraction of the road's length under water, 0..1}}.
RADAR_FLOOD = "radar_flood"
RADAR_FLOOD_FEATURES = {"scene_id": FeatureSpec(type="str"), "area_id": FeatureSpec(type="str")}

# A1: output {"hazards": {hazard name: score, 0..1}}.
REPORT_CLASSIFIER = "report_classifier"
REPORT_CLASSIFIER_FEATURES = {"text": FeatureSpec(type="str")}


def _score(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value) if 0 <= value <= 1 else None


def flooded_edges(prediction: Prediction) -> dict[str, float]:
    """Roads the live radar model puts at or over its threshold. Empty means nothing usable."""
    threshold = prediction.operating_threshold
    edges = (prediction.output or {}).get("edges") if prediction.usable else None
    if threshold is None or not isinstance(edges, dict):
        return {}
    scores = {edge: _score(value) for edge, value in edges.items()}
    if any(score is None for score in scores.values()):
        return {}  # one corrupt value means the layer as a whole cannot be trusted
    return {edge: score for edge, score in scores.items() if score >= threshold}


def report_supports(prediction: Prediction, hazard: str) -> bool:
    """True only when the classifier positively agrees that the report is about this hazard."""
    threshold = prediction.operating_threshold
    hazards = (prediction.output or {}).get("hazards") if prediction.usable else None
    if threshold is None or not isinstance(hazards, dict):
        return False
    score = _score(hazards.get(hazard))
    return score is not None and score >= threshold
