"""The one way agents ask a trained model a question.

``predict()`` always answers, and always says what kind of answer it is. When it cannot use a model
the status says why and ``output`` is None, so a caller keeps its rule-based path: a missing model
must never look like "no hazard" (§5.3, §10). Every call, used or not, is a ledger record carrying
its inputs and the model version (§7.1), so a prediction can later be linked to the outcome.

This module imports no ML library. A predictor is any callable from a feature dict to an output
dict; the code that loads real weights lives elsewhere and is installed from requirements-ml.txt.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any, Callable

from pydantic import BaseModel

from atlas.learning.registry import FeatureSpec, ModelRegistry
from atlas.memory.ledger import Ledger, canonical

Predictor = Callable[[dict[str, Any]], dict[str, Any]]


class PredictionStatus(str, Enum):
    OK = "ok"
    NO_MODEL = "no_model"  # nothing is live, or the live version's weights are not loaded here
    SCHEMA_MISMATCH = "schema_mismatch"  # the input is not what the model was trained on
    MODEL_ERROR = "model_error"  # the model raised or returned something unusable


class Prediction(BaseModel):
    prediction_id: str
    model: str
    version: str | None
    status: PredictionStatus
    reason: str = ""
    output: dict[str, Any] | None = None
    operating_threshold: float | None = None
    made_at: datetime

    @property
    def usable(self) -> bool:
        return self.status is PredictionStatus.OK


def _matches(value: Any, spec: FeatureSpec) -> bool:
    if value is None:
        return spec.nullable
    if spec.type == "bool":
        return isinstance(value, bool)
    if isinstance(value, bool):  # bool is an int in Python; never let it pass as a number
        return False
    if spec.type == "int":
        return isinstance(value, int)
    if spec.type == "float":
        return isinstance(value, (int, float)) and math.isfinite(value)
    return isinstance(value, str)


def schema_problems(features: dict[str, Any], schema: dict[str, FeatureSpec]) -> list[str]:
    """Why these features do not fit the schema; empty when they do."""
    problems = [f"missing:{name}" for name in sorted(set(schema) - set(features))]
    problems += [f"unexpected:{name}" for name in sorted(set(features) - set(schema))]
    problems += [
        f"invalid:{name}"
        for name in sorted(set(schema) & set(features))
        if not _matches(features[name], schema[name])
    ]
    return problems


class Inference:
    def __init__(self, registry: ModelRegistry, ledger: Ledger, *, clock=None):
        self.registry, self.ledger = registry, ledger
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._predictors: dict[tuple[str, str], Predictor] = {}

    def bind(self, name: str, version: str, predictor: Predictor) -> None:
        """Make a registered version callable in this process."""
        if self.registry.get(name, version) is None:
            raise ValueError(f"cannot bind unregistered model {name} {version}")
        self._predictors[(name, version)] = predictor

    def predict(
        self,
        model: str,
        features: dict[str, Any],
        *,
        caller: str,
        evidence_ids: list[str] | tuple[str, ...] = (),
        incident_id: str | None = None,
    ) -> Prediction:
        """Ask the live version of ``model``. Synchronous and safe inside a bus handler."""
        record = self.registry.live(model)
        if record is None:
            return self._log(
                model, None, None, features, caller, evidence_ids, incident_id,
                PredictionStatus.NO_MODEL, "no_live_version", None,
            )
        status, reason, output = self._run(record.name, record.version, record, features)
        return self._log(
            model, record.version, record.operating_threshold, features, caller, evidence_ids,
            incident_id, status, reason, output,
        )

    def _run(self, name, version, record, features):
        predictor = self._predictors.get((name, version))
        if predictor is None:
            return PredictionStatus.NO_MODEL, "live_version_not_loaded", None
        problems = schema_problems(features, record.feature_schema)
        if problems:
            return PredictionStatus.SCHEMA_MISMATCH, ",".join(problems), None
        try:
            output = predictor(dict(features))
            if not isinstance(output, dict):
                raise TypeError("predictor must return a dict")
            canonical(output)  # NaN or an unserialisable value is not a usable answer
        except Exception as exc:  # third-party model code: contain it, the caller has rules
            return PredictionStatus.MODEL_ERROR, type(exc).__name__, None
        return PredictionStatus.OK, "", output

    def _log(
        self, model, version, threshold, features, caller, evidence_ids, incident_id, status,
        reason, output,
    ) -> Prediction:
        made_at = self.clock()
        try:
            canonical(features)
            logged = features
        except (TypeError, ValueError):
            logged = {"_redacted": "unserialisable_features"}
        body = {
            "model": model,
            "version": version,
            "status": status.value,
            "reason": reason,
            "caller": caller,
            "incident_id": incident_id,
            "evidence_ids": list(evidence_ids),
            "features": logged,
            "output": output,
            "operating_threshold": threshold,
            "made_at": made_at.isoformat(),
        }
        # The output is part of the identity: a non-deterministic model called twice at one replay
        # clock tick is two predictions, not a conflicting reuse of one ledger id.
        prediction_id = sha256(canonical(body).encode()).hexdigest()
        self.ledger.append(
            f"prediction:{prediction_id}", "prediction", {"prediction_id": prediction_id, **body}
        )
        return Prediction(
            prediction_id=prediction_id,
            model=model,
            version=version,
            status=status,
            reason=reason,
            output=output,
            operating_threshold=threshold,
            made_at=made_at,
        )

    def trace(self, prediction_id: str) -> dict | None:
        """The ledger payload for one prediction: inputs, evidence, model version and output."""
        record = self.ledger.get(f"prediction:{prediction_id}")
        return record["payload"] if record else None
