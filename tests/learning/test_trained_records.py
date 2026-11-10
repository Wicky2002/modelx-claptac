from atlas.learning import ModelStatus
from atlas.learning.contracts import RADAR_FLOOD, REPORT_CLASSIFIER
from atlas.learning.trained import TRAINED, register_trained


def test_trained_models_register_as_candidates_and_repeat_safely(runtime):
    first = register_trained(runtime.models)
    again = register_trained(runtime.models)
    assert [r.version for r in first] == [r.version for r in again]
    records = runtime.models.list()
    assert len(records) == len(TRAINED) == 4
    assert {r.status for r in records} == {ModelStatus.CANDIDATE}
    assert {r.name for r in records} == {RADAR_FLOOD, REPORT_CLASSIFIER}
    assert all(r.artifact_uri.startswith("not-deployed") for r in records)


def test_registered_records_never_answer_predictions(runtime):
    register_trained(runtime.models)
    flood = runtime.inference.predict(RADAR_FLOOD, {"scene_id": "s", "area_id": "a"}, caller="test")
    report = runtime.inference.predict(REPORT_CLASSIFIER, {"text": "flood"}, caller="test")
    assert not flood.usable and not report.usable
