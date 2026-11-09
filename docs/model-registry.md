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
| `shadow` | runs beside the live model, never acted on | `retired`; `live` with human approval |
| `live` | the one version `predict()` uses (the database enforces at most one) | replaced by promotion or rollback |
| `retired` | no longer used | `live` only as a rollback target |

Making a version live retires the previous live version in the same transaction.

## A10 Data & Learning, promotion and rollback

`system.learning` (A10, `atlas/agents/a10_data_learning.py`) has read-only views of the registry and
ledger and can publish events. It holds nothing that can change a model.

- `drift(name)` compares the features the live model has received with `feature_stats` from training.
- `shadow_summary(name, version)` compares a shadow version with the live one on the same inputs.
- `review(name)` publishes both as a `MODEL_REVIEW` event.
- `request_promotion(name, version)` and `request_rollback(name)` send a proposal to the Gateway.

**How A10's request reaches the Gateway.** `policy.yaml` keeps A3 as the only general proposer. An
action can name its own `proposers`, and `promote_model` and `rollback_model` name only A10. So A10
can ask for those two things and nothing else, and A3 cannot ask for them. A10 uses the normal
`PLAN_PROPOSED` route, and the `model_registry` executor carries out the change.

Both actions are always high consequence. As a second check that does not depend on the policy file,
`ModelRegistry.promote()` and `rollback()` refuse unless the ledger holds a human approval for exactly
that version. Rollback is one step: it restores the version the last promotion replaced, then there
is nothing further to roll back to.

Shadow versions run inside `predict()` on the same input and are logged as `shadow_prediction`
records. Their output is never returned to a caller.

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

## What the agents use models for

The feature and output contracts are in `atlas/learning/contracts.py`. A wrapper around a trained
model must match them, or the agent treats the answer as "the model said nothing".

| Model name | Caller | Features | Output | Effect |
|---|---|---|---|---|
| `radar_flood` | A2, on a `FLOOD_SCENE` event | `scene_id`, `area_id` | `{"edges": {edge_id: fraction 0..1}}` | Roads at or over the threshold reach A4 as closure evidence |
| `report_classifier` | A1, on a field report with text | `text` | `{"hazards": {name: score 0..1}}` | Agreement adds 0.1 to the report's confidence, like one corroborating source |

Limits on what a model can do:

- The rules decide when an alarm goes off. A model cannot raise a trigger on its own or hold one
  back, and it never changes an A2 risk level, so warning floors stay in place.
- A radar scene can only add evidence that a road is closed. A dry result says nothing, because
  it could not reopen a road a gauge has closed.
- A scene never overrides evidence about a road that is newer than its acquisition time.
- Forecasts from the Mawiongrim study (H4) are not connected to anything: that dataset has no
  landslide events.

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
