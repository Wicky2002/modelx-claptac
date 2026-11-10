"""Stand-in models for checking the system still works with a model in the loop.

These are not trained and their numbers mean nothing: the classifier agrees with every report, and
the radar model finds nothing. They exist only inside an isolated benchmark runtime.
"""

from __future__ import annotations

from atlas.learning import ModelSpec, ModelStatus
from atlas.learning.contracts import (
    RADAR_FLOOD,
    RADAR_FLOOD_FEATURES,
    REPORT_CLASSIFIER,
    REPORT_CLASSIFIER_FEATURES,
)
from atlas.learning.registry import promotion_key

VERSION = "stand-in"


def install(runtime) -> None:
    models = (
        (RADAR_FLOOD, RADAR_FLOOD_FEATURES, lambda features: {"edges": {}}),
        (
            REPORT_CLASSIFIER,
            REPORT_CLASSIFIER_FEATURES,
            lambda features: {"hazards": {h: 0.9 for h in ("flood", "landslide", "earthquake")}},
        ),
    )
    for name, features, predictor in models:
        runtime.models.register(
            ModelSpec(
                name=name,
                version=VERSION,
                task="benchmark stand-in, untrained",
                feature_schema=features,
                dataset_versions={"none": "stand-in"},
                metrics={"untrained": 0.0},
                operating_threshold=0.5,
            )
        )
        runtime.models.set_status(name, VERSION, ModelStatus.SHADOW, actor="benchmark")
        # This runtime and its ledger exist only for one benchmark case.
        runtime.ledger.append(
            f"action:{promotion_key(name, VERSION)}:approved",
            "action",
            {"phase": "approved", "reviewer": "benchmark-stand-in"},
        )
        runtime.models.promote(name, VERSION, actor="benchmark")
        runtime.inference.bind(name, VERSION, predictor)
