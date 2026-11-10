"""The trained models' registry records, so model review shows what was actually trained.

The weights stay outside git and off the server, so these versions are registered as candidates and
never bound to a predictor: predict() keeps answering "no model", and the agents keep their rules.
The metrics are the held-out results in docs/evaluation.md. Each test set was scored once.

Registering is idempotent, so it runs on every start. Turned on with ATLAS_REGISTER_TRAINED_MODELS=1
(set in the Docker image).
"""

from __future__ import annotations

from atlas.learning.contracts import (
    RADAR_FLOOD,
    RADAR_FLOOD_FEATURES,
    REPORT_CLASSIFIER,
    REPORT_CLASSIFIER_FEATURES,
)
from atlas.learning.registry import ModelSpec

NOT_DEPLOYED = "not-deployed:weights-kept-outside-git"
MMFLOOD = {"mmflood": "1.0.0, MMFlood event splits (54 train, 7 val, 34 test events)"}
NEWS = {"disaster-news": "data/splits/disaster-news.json (770 test articles, English only)"}

TRAINED = (
    ModelSpec(
        name=RADAR_FLOOD,
        version="d2-ensemble-3",
        task=(
            "Sentinel-1 flood mapping, per pixel: three U-Nets averaged (two ResNet-34, one ResNet-50), "
            "no flood on slopes over 10 degrees, temperature-calibrated. Threshold is a pixel "
            "probability; the road-edge wrapper is not written yet."
        ),
        feature_schema=RADAR_FLOOD_FEATURES,
        dataset_versions=MMFLOOD,
        metrics={
            "val_mean_event_f1": 0.4108,
            "test_mean_event_f1": 0.3403,
            "test_pixel_f1": 0.4965,
            "test_pixel_iou": 0.3303,
            "test_baseline_mean_event_f1": 0.215,
            "test_baseline_pixel_f1": 0.301,
            "test_calibration_error": 0.0195,
        },
        operating_threshold=0.034,
        artifact_uri=NOT_DEPLOYED,
    ),
    ModelSpec(
        name=RADAR_FLOOD,
        version="d2-unet-r34",
        task=(
            "Sentinel-1 flood mapping, per pixel: one U-Net (ResNet-34) on VV, VH, elevation, "
            "hydrography and permanent water. Threshold is a pixel probability; the road-edge wrapper "
            "is not written yet."
        ),
        feature_schema=RADAR_FLOOD_FEATURES,
        dataset_versions=MMFLOOD,
        metrics={
            "val_mean_event_f1": 0.4029,
            "val_pixel_f1": 0.4625,
            "val_pixel_iou": 0.3008,
            "val_baseline_mean_event_f1": 0.1976,
        },
        operating_threshold=0.034,
        artifact_uri=NOT_DEPLOYED,
    ),
    ModelSpec(
        name=REPORT_CLASSIFIER,
        version="d4-hybrid",
        task=(
            "Disaster-news reading: keyword rules or the transformer per hazard, chosen on validation, "
            "with the transformer for location and impact sentences."
        ),
        feature_schema=REPORT_CLASSIFIER_FEATURES,
        dataset_versions=NEWS,
        metrics={
            "val_hazard_macro_f1": 0.878,
            "test_hazard_macro_f1": 0.862,
            "test_location_sentence_f1": 0.948,
            "test_impact_sentence_f1": 0.988,
        },
        operating_threshold=None,
        artifact_uri=NOT_DEPLOYED,
    ),    ModelSpec(
        name=REPORT_CLASSIFIER,
        version="d4-xlmr",
        task=(
            "Disaster-news reading: XLM-RoBERTa scoring eight hazards per article, and location and "
            "impact sentences. Labels appear machine-generated, so scores measure agreement with them."
        ),
        feature_schema=REPORT_CLASSIFIER_FEATURES,
        dataset_versions=NEWS,
        metrics={
            "test_hazard_macro_f1": 0.667,
            "test_location_sentence_f1": 0.948,
            "test_impact_sentence_f1": 0.988,
            "test_keyword_baseline_hazard_macro_f1": 0.866,
        },
        operating_threshold=None,
        artifact_uri=NOT_DEPLOYED,
    ),
)


def register_trained(registry) -> list:
    return [registry.register(spec) for spec in TRAINED]
