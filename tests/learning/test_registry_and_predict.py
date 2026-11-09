import subprocess
import sys

import pytest
from pydantic import ValidationError

from atlas.learning import (
    FeatureSpec,
    ModelSpec,
    ModelStatus,
    PredictionStatus,
    RegistryError,
)
from tests.model_helpers import promote_with_approval


def spec(version="v1", **changes):
    return ModelSpec(
        **{
            "name": "dummy",
            "version": version,
            "task": "test",
            "feature_schema": {
                "rain": FeatureSpec(type="float"),
                "slope": FeatureSpec(type="float", nullable=True),
            },
            "dataset_versions": {"sample": "1"},
            "metrics": {"f1": 0.5},
            "operating_threshold": 0.4,
            **changes,
        }
    )


def make_live(runtime, version="v1", predictor=None):
    runtime.models.register(spec(version))
    promote_with_approval(runtime, "dummy", version)
    runtime.inference.bind("dummy", version, predictor or (lambda f: {"score": f["rain"] / 10}))


GOOD = {"rain": 5.0, "slope": None}


def test_done_when_registered_called_and_traced_in_the_ledger(runtime):
    make_live(runtime)
    result = runtime.inference.predict(
        "dummy", GOOD, caller="a1_sentinel", evidence_ids=["e1"], incident_id="incident:x"
    )
    assert result.usable and result.output == {"score": 0.5}
    assert result.version == "v1" and result.operating_threshold == 0.4
    trace = runtime.inference.trace(result.prediction_id)
    assert trace["features"] == GOOD
    assert trace["evidence_ids"] == ["e1"]
    assert trace["version"] == "v1"
    assert trace["caller"] == "a1_sentinel"
    assert trace["output"] == {"score": 0.5}
    assert runtime.ledger.verify()


def test_no_live_model_reports_no_model_and_is_logged(runtime):
    result = runtime.inference.predict("dummy", GOOD, caller="a1")
    assert result.status is PredictionStatus.NO_MODEL and result.output is None
    assert not result.usable
    assert runtime.inference.trace(result.prediction_id)["reason"] == "no_live_version"


@pytest.mark.parametrize("status", ["candidate", "shadow"])
def test_only_a_live_version_answers(runtime, status):
    runtime.models.register(spec())
    runtime.inference.bind("dummy", "v1", lambda f: {"score": 1.0})
    if status == "shadow":
        runtime.models.set_status("dummy", "v1", ModelStatus.SHADOW, actor="test")
    assert runtime.inference.predict("dummy", GOOD, caller="a1").status is PredictionStatus.NO_MODEL


def test_live_but_not_loaded_is_no_model(runtime):
    make_live(runtime)
    runtime.inference._predictors.clear()
    result = runtime.inference.predict("dummy", GOOD, caller="a1")
    assert result.status is PredictionStatus.NO_MODEL
    assert result.reason == "live_version_not_loaded"


@pytest.mark.parametrize(
    "features, reason",
    [
        ({"rain": 1.0}, "missing:slope"),
        ({**GOOD, "extra": 1.0}, "unexpected:extra"),
        ({"rain": None, "slope": 1.0}, "invalid:rain"),  # missing is not silently zero
        ({"rain": True, "slope": 1.0}, "invalid:rain"),
        ({"rain": float("nan"), "slope": 1.0}, "invalid:rain"),
    ],
)
def test_schema_mismatch_never_reaches_the_model(runtime, features, reason):
    called = []
    make_live(runtime, predictor=lambda f: called.append(f) or {"score": 1.0})
    result = runtime.inference.predict("dummy", features, caller="a1")
    assert result.status is PredictionStatus.SCHEMA_MISMATCH
    assert result.reason == reason and result.output is None and not called
    assert runtime.ledger.verify()  # NaN inputs must not break the ledger


def boom(_):
    raise RuntimeError("weights corrupt")


@pytest.mark.parametrize(
    "predictor", [boom, lambda f: {"score": float("nan")}, lambda f: 0.5, lambda f: {"x": object()}]
)
def test_broken_model_is_contained(runtime, predictor):
    make_live(runtime, predictor=predictor)
    result = runtime.inference.predict("dummy", GOOD, caller="a1")
    assert result.status is PredictionStatus.MODEL_ERROR and result.output is None
    assert runtime.inference.trace(result.prediction_id)["status"] == "model_error"


def test_nondeterministic_model_at_one_clock_tick_does_not_collide(runtime):
    values = iter([0.1, 0.2])
    make_live(runtime, predictor=lambda f: {"score": next(values)})
    first = runtime.inference.predict("dummy", GOOD, caller="a1")
    second = runtime.inference.predict("dummy", GOOD, caller="a1")
    assert first.prediction_id != second.prediction_id


def test_a_new_live_version_retires_the_old_one(runtime):
    make_live(runtime, "v1")
    make_live(runtime, "v2")
    assert runtime.models.live("dummy").version == "v2"
    assert runtime.models.get("dummy", "v1").status is ModelStatus.RETIRED
    moves = [r["payload"] for r in runtime.ledger.records("model")]
    assert any(m.get("to") == "retired" and m["version"] == "v1" for m in moves)


def test_registration_is_idempotent_but_immutable(runtime):
    runtime.models.register(spec())
    runtime.models.register(spec())
    assert len(runtime.models.list("dummy")) == 1
    with pytest.raises(RegistryError):
        runtime.models.register(spec(metrics={"f1": 0.99}))


def test_lifecycle_cannot_skip_shadow_or_leave_retired(runtime):
    runtime.models.register(spec())
    with pytest.raises(RegistryError):
        runtime.models.set_status("dummy", "v1", ModelStatus.LIVE, actor="test")
    runtime.models.set_status("dummy", "v1", ModelStatus.RETIRED, actor="test")
    with pytest.raises(RegistryError):
        runtime.models.set_status("dummy", "v1", ModelStatus.SHADOW, actor="test")


@pytest.mark.parametrize(
    "missing", ["feature_schema", "dataset_versions", "metrics", "operating_threshold"]
)
def test_undocumented_model_cannot_be_registered(missing):
    fields = spec().model_dump()
    del fields[missing]
    with pytest.raises(ValidationError):
        ModelSpec(**fields)


def test_binding_an_unregistered_version_is_refused(runtime):
    with pytest.raises(ValueError):
        runtime.inference.bind("ghost", "v1", lambda f: {})


def test_importing_the_package_loads_no_ml_library():
    code = (
        "import sys, atlas.learning;"
        "print([m for m in ('torch','lightgbm','transformers','rasterio') if m in sys.modules])"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
