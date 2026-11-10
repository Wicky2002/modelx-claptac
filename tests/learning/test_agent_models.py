"""S2's done-when: a replay runs with and without models, and the fallback is covered."""

from datetime import timedelta

import pytest

from atlas.core.config import SentinelConfig, Settings
from atlas.ingest.simulator import ReplayClock, replay
from atlas.learning import ModelSpec
from atlas.learning.contracts import (
    RADAR_FLOOD,
    RADAR_FLOOD_FEATURES,
    REPORT_CLASSIFIER,
    REPORT_CLASSIFIER_FEATURES,
)
from atlas.runtime import Runtime
from atlas.system import attach_all
from tests.control.conftest import fast_policy
from tests.model_helpers import promote_with_approval

AREA = "ratnapura-demo-river"
LOC = {"lat": 6.6828, "lon": 80.3992, "area_id": AREA}


def live(runtime, name, features, predictor, threshold=0.5):
    runtime.models.register(
        ModelSpec(
            name=name,
            version="v1",
            task="test double",
            feature_schema=features,
            dataset_versions={"sample": "1"},
            metrics={"f1": 0.5},
            operating_threshold=threshold,
        )
    )
    promote_with_approval(runtime, name, "v1")
    runtime.inference.bind(name, "v1", predictor)


@pytest.fixture
def world():
    clock = ReplayClock()
    runtime = Runtime(
        Settings(database_path=":memory:", sentinel=SentinelConfig(reasoning_enabled=True)),
        clock=clock,
    )
    system = attach_all(runtime, policy=fast_policy())
    yield runtime, system, clock
    runtime.db.close()


def sensor(at, value):
    return {
        "at_seconds": at,
        "payload": {
            "kind": "sensor",
            "node_id": "rtp-node-01",
            "sensor_id": "wl-01",
            "type": "water_level",
            "value": value,
            "unit": "cm",
            "location": LOC,
        },
    }


def field_report(at, text="The river has flooded the main road", value=5):
    return {
        "at_seconds": at,
        "payload": {
            "source": "community",
            "kind": "field_report",
            "area_id": AREA,
            "attribute": "water_level",
            "value": value,
            "unit": "cm",
            "text": text,
        },
    }


def scene(at, observed=None):
    return {
        "at_seconds": at,
        "observed_seconds": at if observed is None else observed,
        "payload": {"kind": "flood_scene", "scene_id": "s1", "area_id": AREA},
    }


def payloads(runtime, kind, sub=None):
    found = [r["payload"] for r in runtime.ledger.records("event") if r["payload"]["type"] == kind]
    return [e["payload"] for e in found if sub is None or e["payload"].get("kind") == sub]


def edges(system, count=3):
    return sorted(system.routing.evacuation._index)[:count]


def radar(system, fraction=0.9):
    flooded = {e: fraction for e in edges(system)}
    return lambda features: {"edges": flooded}


def classifier(score=0.9):
    return lambda features: {"hazards": {"flood": score}}


def belief(runtime, edge):
    found = runtime.cop.get(f"edge:{edge}", "belief_open", include_stale=True)
    return found.value if found else None


SCENARIO = {"name": "t", "events": [sensor(0, 10), field_report(30), scene(60)]}


async def test_replay_without_models_keeps_the_rules_and_logs_why(world):
    runtime, system, clock = world
    await runtime.start()
    await replay(runtime, SCENARIO, clock)
    assert not payloads(runtime, "risk_update", "road_flood_evidence")
    assert all(belief(runtime, e) is None for e in edges(system))
    logged = [r["payload"] for r in runtime.ledger.records("prediction")]
    assert {p["model"] for p in logged} == {RADAR_FLOOD, REPORT_CLASSIFIER}
    assert {p["status"] for p in logged} == {"no_model"}
    assert runtime.ledger.verify()


async def test_replay_with_models_feeds_a4_and_traces_the_prediction(world):
    runtime, system, clock = world
    live(runtime, RADAR_FLOOD, RADAR_FLOOD_FEATURES, radar(system))
    live(runtime, REPORT_CLASSIFIER, REPORT_CLASSIFIER_FEATURES, classifier())
    await runtime.start()
    await replay(runtime, SCENARIO, clock)
    (evidence,) = payloads(runtime, "risk_update", "road_flood_evidence")
    assert set(evidence["flooded"]) == set(edges(system))
    assert runtime.inference.trace(evidence["prediction_id"])["version"] == "v1"
    assert all(belief(runtime, e) < 0.5 for e in edges(system))
    assert f"prediction:{evidence['prediction_id']}" in runtime.cop.get(
        f"edge:{edges(system)[0]}", "belief_open", include_stale=True
    ).provenance
    assert runtime.ledger.verify()


def validated_report_confidence(runtime):
    return [
        o["confidence"]
        for o in payloads(runtime, "observation_validated")
        if o["source"] == "community"
    ]


async def test_classifier_agreement_raises_field_report_confidence(world):
    runtime, system, clock = world
    live(runtime, REPORT_CLASSIFIER, REPORT_CLASSIFIER_FEATURES, classifier())
    await runtime.start()
    await replay(runtime, {"name": "t", "events": [field_report(0)]}, clock)
    assert validated_report_confidence(runtime) == [pytest.approx(0.6)]


@pytest.mark.parametrize("predictor", [classifier(0.1), lambda f: {"unexpected": 1}])
async def test_a_disagreeing_or_odd_classifier_changes_nothing(world, predictor):
    runtime, system, clock = world
    live(runtime, REPORT_CLASSIFIER, REPORT_CLASSIFIER_FEATURES, predictor)
    await runtime.start()
    await replay(runtime, {"name": "t", "events": [field_report(0)]}, clock)
    assert validated_report_confidence(runtime) == [pytest.approx(0.5)]


async def test_the_classifier_cannot_raise_an_alarm_alone(world):
    runtime, system, clock = world
    runtime.sentinel.config.source_reliability["community"] = 0.6  # 0.7 with support, gate is 0.65
    live(runtime, REPORT_CLASSIFIER, REPORT_CLASSIFIER_FEATURES, classifier())
    await runtime.start()
    await replay(runtime, {"name": "t", "events": [field_report(0, value=30)]}, clock)
    assert validated_report_confidence(runtime) == [pytest.approx(0.7)]
    assert not payloads(runtime, "trigger")


async def test_a_broken_model_cannot_suppress_a_rule_warning(world):
    runtime, system, clock = world

    def broken(features):
        raise RuntimeError("weights corrupt")

    live(runtime, RADAR_FLOOD, RADAR_FLOOD_FEATURES, broken)
    live(runtime, REPORT_CLASSIFIER, REPORT_CLASSIFIER_FEATURES, broken)
    await runtime.start()
    await replay(runtime, {"name": "t", "events": [scene(0), sensor(10, 30)]}, clock)
    assert payloads(runtime, "trigger")
    assert system.orchestration.hazard.levels(AREA)["flood"] == "warning"
    assert {r["payload"]["status"] for r in runtime.ledger.records("prediction")} == {"model_error"}


async def test_dry_radar_cannot_lower_a_level_or_reopen_a_road(world):
    runtime, system, clock = world
    live(runtime, RADAR_FLOOD, RADAR_FLOOD_FEATURES, radar(system, fraction=0.0))
    await runtime.start()
    await replay(runtime, {"name": "t", "events": [sensor(0, 30)]}, clock)
    level = system.orchestration.hazard.levels(AREA)["flood"]
    closed = {e: belief(runtime, e) for e in system.routing.evacuation._index}
    await replay(runtime, {"name": "t", "events": [scene(60)]}, clock)
    assert system.orchestration.hazard.levels(AREA)["flood"] == level
    assert {e: belief(runtime, e) for e in closed} == closed
    assert not payloads(runtime, "risk_update", "road_flood_evidence")


@pytest.mark.parametrize("flooded", [{"e": float("inf")}, {"e": 2.0}, {"e": "wet"}, []])
async def test_a_corrupt_layer_is_not_used(world, flooded):
    runtime, system, clock = world
    # inf is refused as a model_error, the others by the contract reader
    live(runtime, RADAR_FLOOD, RADAR_FLOOD_FEATURES, lambda f: {"edges": flooded})
    await runtime.start()
    await replay(runtime, {"name": "t", "events": [scene(0)]}, clock)
    assert not payloads(runtime, "risk_update", "road_flood_evidence")


async def test_an_older_scene_does_not_override_newer_road_evidence(world):
    runtime, system, clock = world
    target = edges(system, 1)[0]
    live(runtime, RADAR_FLOOD, RADAR_FLOOD_FEATURES, lambda f: {"edges": {target: 0.9}})
    await runtime.start()
    from atlas.core.events import Belief

    runtime.cop.put(
        Belief(
            subject=f"edge:{target}",
            attribute="belief_open",
            value=0.95,
            confidence=0.9,
            updated_at=clock.now + timedelta(minutes=30),
        )
    )
    # Published at +60 min, but acquired at +1 min: before the road's last report.
    await replay(runtime, {"name": "t", "events": [scene(3600, observed=60)]}, clock)
    assert belief(runtime, target) == 0.95
