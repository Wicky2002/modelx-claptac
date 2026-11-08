"""The console must not turn rehearsal data, expired evidence or sends into facts."""

import json
from datetime import timedelta

from fastapi.testclient import TestClient

from atlas.api.main import create_app
from atlas.core.config import Settings
from atlas.core.events import Belief, Event, EventType
from atlas.dashboard.dev.geo_view import situation_map
from atlas.dashboard.dev.information import Information
from atlas.dashboard.dev.playground import LiveReplay
from atlas.memory.evidence_store import EvidenceStore


async def test_status_dimensions_compose_and_do_not_change_evidence(runtime, clock):
    store = EvidenceStore(runtime.db)
    original = {
        "source": "sensor:demo",
        "payload": {
            "timestamp": clock().isoformat(),
            "value": 12,
            "_replay": {"scenario": "flood", "synthetic": True},
        },
    }
    ref = store.put(original)
    await runtime.bus.publish(
        Event(type=EventType.CONFLICT_FLAG, source="a1_sentinel", payload={"evidence_ids": [ref]})
    )
    clock.now += timedelta(seconds=601)
    info = Information(runtime).describe("observed", refs=[ref])
    assert set(info["labels"]) == {"observed", "disputed", "stale", "synthetic", "replay"}
    assert info["age_seconds"] == 601
    assert store.get(ref, role="auditor") == original


def test_expired_road_evidence_stays_visible_as_stale(system, runtime, clock):
    edge = situation_map(system)["edges"][0]
    runtime.cop.put(
        Belief(
            subject="edge:" + edge["id"],
            attribute="belief_open",
            value=0.1,
            confidence=0.7,
            updated_at=clock() - timedelta(seconds=600),
            ttl_seconds=60,
        )
    )
    view = situation_map(system)
    road = next(e for e in view["edges"] if e["id"] == edge["id"])
    assert road["belief_open"] == 0.1
    assert {"inferred", "stale"} <= set(road["information"]["labels"])
    assert all("synthetic" in s["information"]["labels"] for s in view["shelters"])
    assert all(s["occupancy"] is None for s in view["shelters"])


def test_replay_context_survives_restart_and_does_not_claim_to_be_running(tmp_path):
    path = str(tmp_path / "console.db")
    with TestClient(create_app(Settings(database_path=path))) as client:
        state = client.post(
            "/play/scenarios/start",
            json={
                "scenario": "ratnapura_ditwah_2025",
                "speed": 0.1,
            },
        ).json()
        assert state["contains_replay"]
        assert state["simulated_at"].startswith("2025-11-27")
        stopped = client.post("/play/scenarios/stop").json()
        assert stopped["state"] == "stopped" and stopped["contains_replay"]
    with TestClient(create_app(Settings(database_path=path))) as client:
        state = client.get("/dev/context").json()
        assert state["state"] == "stopped" and state["contains_replay"]


def test_recovered_running_replay_is_interrupted(runtime):
    replay = LiveReplay(runtime)
    replay.state = {"state": "running", "scenario": "flood", "elapsed_seconds": 12}
    replay._save()
    recovered = LiveReplay(runtime).status()
    assert recovered["state"] == "interrupted" and recovered["elapsed_seconds"] == 12


def test_workflow_labels_never_claim_execution_or_delivery(runtime):
    info = Information(runtime)
    proposed = info.event({"type": "plan_proposed"})
    authorised = info.event({"type": "action_authorised"})
    sent = info.event({"type": "alert_published"})
    assert "not approval" in proposed["workflow"]
    assert "execution is a separate event" in authorised["workflow"]
    assert "acknowledgement unavailable" in sent["workflow"]


def test_new_read_endpoints_require_existing_permissions(monkeypatch):
    monkeypatch.setenv("ATLAS_AUTH", "strict")
    monkeypatch.setenv(
        "ATLAS_TOKENS",
        json.dumps(
            [
                {"token": "view", "name": "Viewer", "role": "viewer"},
            ]
        ),
    )
    with TestClient(create_app(Settings(database_path=":memory:"))) as client:
        assert client.get("/dev/context").status_code == 401
        assert client.get("/dev/evidence/missing").status_code == 401
        headers = {"X-Operator-Token": "view"}
        assert client.get("/dev/context", headers=headers).status_code == 200
        assert client.get("/dev/evidence/missing", headers=headers).status_code == 404


async def test_derived_events_keep_replay_identity_without_labelling_live_inputs(
    runtime, system, clock
):
    from atlas.dashboard.dev.playground import _event_for
    from atlas.dashboard.dev.timeline import timeline
    from tests.orchestration.conftest import reading

    event = _event_for(reading(0, 30)["payload"], clock(), 0)
    event.payload["_replay"] = {"scenario": "exercise", "synthetic": True}
    await runtime.bus.publish(event)
    events = timeline(runtime, limit=500)["events"]
    derived = [e for e in events if e["type"] == "observation_validated"]
    assert derived and all("replay" in e["information"]["labels"] for e in derived)
    live = _event_for(reading(0, 10, node="live-gauge")["payload"], clock(), 1)
    await runtime.bus.publish(live)
    current = next(e for e in timeline(runtime, limit=500)["events"] if e["id"] == live.id)
    assert "replay" not in current["information"]["labels"]
