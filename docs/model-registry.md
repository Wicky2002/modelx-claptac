# Model registry and `predict()`

`atlas/learning` records which trained models exist and is the only way an agent calls one.
`atlas/manager/registry.py` is a different thing: it tracks agents.

## Registering a version

```python
from atlas.learning import FeatureSpec, ModelSpec

runtime.models.register(ModelSpec(
    name="radar_flood",
    version="2026-11-01",
    task="flood-class segmentation of Sentinel-1 tiles",
    feature_schema={"flood_fraction": FeatureSpec(type="float"),
                    "hydrography": FeatureSpec(type="float", nullable=True)},
    dataset_versions={"mmflood": "1.0"},
    metrics={"iou_flood_test": 0.61},
    operating_threshold=0.5,            # chosen on validation only; None if the model has none
    artifact_uri="drive://models/radar_flood/2026-11-01",  # weights never go in git
))
```

Every field except `artifact_uri` is required. A version's record cannot be changed after
registration: register a new version instead.

| Status | Meaning | May move to |
|---|---|---|
| `candidate` | registered, answers nobody | `shadow`, `retired` |
| `shadow` | may run beside the live model, never acted on | `live`, `retired` |
| `live` | the one version `predict()` uses (the database enforces at most one) | `retired` |
| `retired` | no longer used | none |

Making a version live retires the previous live version in the same transaction.

## Calling a model

```python
runtime.inference.bind("radar_flood", "2026-11-01", predictor)  # any dict -> dict callable

result = runtime.inference.predict(
    "radar_flood", features, caller="a2_hazard_intel", evidence_ids=evidence, incident_id=incident
)
if result.usable:
    ...  # result.output, result.version, result.operating_threshold
else:
    ...  # keep today's rules
```

`predict()` does not raise for a model problem, and it never makes up an answer. When `status` is
not `ok`, `output` is `None`. **None of these statuses means "no hazard".**

| `status` | Why |
|---|---|
| `ok` | the live version answered |
| `no_model` | nothing is live (`no_live_version`), or its weights are not loaded in this process (`live_version_not_loaded`) |
| `schema_mismatch` | missing, unexpected or wrongly typed features, listed in `reason` |
| `model_error` | the model raised, or returned something that is not a JSON-safe dict |

A feature that can be missing is declared `nullable` and sent as `None`, so missing stays different
from zero. NaN and infinity are always rejected.

## Tracing

Every call, including the ones that could not use a model, is a ledger record of kind `prediction`
holding the features, evidence ids, caller, incident, model version, output and threshold.
Registrations and status changes are records of kind `model`.

```python
runtime.inference.trace(result.prediction_id)
```

Read-only API: `GET /models`, `GET /predictions/{id}`.

## Dependencies

`atlas.learning` imports no ML library, so the Docker demo stays on `requirements.txt`. Code that
loads real weights needs `pip install -r requirements-ml.txt`.
