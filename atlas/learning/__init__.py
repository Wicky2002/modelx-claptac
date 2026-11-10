"""Trained-model lifecycle and inference. Importing this package loads no ML library."""

from atlas.learning.inference import Inference, Prediction, PredictionStatus
from atlas.learning.registry import (
    FeatureSpec,
    ModelRecord,
    ModelRegistry,
    ModelSpec,
    ModelStatus,
    RegistryError,
)

__all__ = [
    "FeatureSpec",
    "Inference",
    "ModelRecord",
    "ModelRegistry",
    "ModelSpec",
    "ModelStatus",
    "Prediction",
    "PredictionStatus",
    "RegistryError",
]
