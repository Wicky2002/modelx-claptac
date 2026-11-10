import json
from datetime import timedelta

from fastapi.testclient import TestClient

from atlas.api.main import create_app
from atlas.core.config import Settings
from atlas.core.events import Event, EventType
from atlas.dashboard.dev.information import stamp
from atlas.dashboard.dev.operations import incident_operations, source_health
from tests.api.test_control_api import action, propose
from tests.conftest import sensor
from tests.dev.test_trace import loop


async def test_source_age_arrival_and_last_accepted_are_distinct(runtime, clock):
    await runtime.start()
    event = sensor(clock, 10, offset=-20)
    event.created_at = clock()
    await runtime.bus.publish(event)
    first = source_health(runtime)["sources"][0]
    assert first["age_seconds"] == 20
    assert first["observed_at"] != first["arrived_at"]
    assert stamp(first["last_accepted_at"]) == clock()
    assert first["last_successful_refresh"] is None
    clock.now += timedelta(seconds=10)
    event = sensor(clock, 80, offset=-600)
    event.created_at = clock()
    await runtime.bus.publish(event)
    latest = source_health(runtime)["sources"][0]
    assert latest["status"] == "stale_or_future"
    assert latest["last_accepted_at"] == first["last_accepted_at"]
    assert latest["age_seconds"] == 600
    assert "stale" in latest["information"]["labels"]


async def test_rejected_duplicate_does_not_look_like_a_new_success(runtime, clock):
    await runtime.start()
    first = sensor(clock, 10)
    first.created_at = clock()
    await runtime.bus.publish(first)
    clock.now += timedelta(seconds=10)
    await runtime.bus.publish(
        Event(
            type=EventType.OBSERVATION,
            source=first.source,
            payload=first.payload,
            created_at=clock(),
        )
    )
    source = source_health(runtime)["sources"][0]
    assert source["status"] == "duplicate"
    assert stamp(source["last_accepted_at"]) == clock() - timedelta(seconds=10)


async def test_bad_source_timestamp_is_unknown_instead_of_breaking_health(runtime):
    await runtime.start()
    await runtime.bus.publish(
        Event(type=EventType.OBSERVATION, source="invalid", payload={"timestamp": "invalid"})
    )
    source = source_health(runtime)["sources"][0]
    assert source["observed_at"] is None and source["age_seconds"] is None
    assert source["status"] == "invalid_schema"


async def test_incident_context_keeps_conflict_values_routes_and_shortages(system, runtime, clock):
    await loop(system, runtime, clock)
    iid = system.orchestration.commander.incidents()[0]["incident_id"]
    state = system.orchestration.commander.get_incident(iid)
    state["plans"]["a6_logistics"]["shortages"] = [
        {"kind": "rescue_team", "demanded": 3, "available": 1, "unmet_jobs": ["rescue"]}
    ]
    system.orchestration.commander._save(state)
    refs = [r[0] for r in runtime.db.connection.execute("SELECT id FROM evidence LIMIT 2")]
    await runtime.bus.publish(
        Event(
            type=EventType.CONFLICT_FLAG,
            source="a1_sentinel",
            payload={
                "area_id": state["area_id"],
                "attribute": "water_level",
                "evidence_ids": refs,
            },
        )
    )
    context = incident_operations(system, iid)
    assert context["area_id"] == state["area_id"]
    assert context["route_plan"]["options"] == state["plans"]["a4_evacuation"]["options"]
    assert context["logistics_plans"][0]["shortages"][0]["demanded"] == 3
    assert len(context["conflicts"][0]["reports"]) == 2
    assert all("disputed" in r["information"]["labels"] for r in context["conflicts"][0]["reports"])
    assert context["changes"] and context["approvals"]
    assert incident_operations(system, "unknown") is None


def test_preview_matches_publication_without_sending_or_resolving():
    with TestClient(create_app(Settings(database_path=":memory:"))) as client:
        params = {
            "area": "Ratnapura",
            "event": "flood",
            "severity": "Severe",
            "expires_minutes": 45,
        }
        propose(client, action("preview", "a9_comms", "publish_alert", params))
        item = client.get("/approvals").json()[0]
        runtime = client.app.state.runtime
        before = runtime.db.connection.total_changes
        result = client.get(f"/approvals/{item['id']}/preview")
        assert result.status_code == 200
        preview = result.json()
        assert preview["target_area"] == "Ratnapura" and preview["expires_minutes"] == 45
        assert set(preview["texts"]) == {"si", "ta", "en"}
        assert runtime.db.connection.total_changes == before
        assert client.get("/alerts").json() == []
        assert client.get("/approvals").json()[0]["status"] == "pending"
        published = client.portal.call(
            client.app.state.control.comms._compose,
            "flood",
            "Ratnapura",
            "Severe",
            ["si", "ta", "en"],
            "evacuate",
            None,
        )
        assert preview["texts"] == published[0]


def test_preview_never_calls_translator_and_reports_missing_languages():
    class ForbiddenTranslator:
        async def translate(self, *args):
            raise AssertionError("Preview must not call a model")

    with TestClient(create_app(Settings(database_path=":memory:"))) as client:
        client.app.state.control.comms.translator = ForbiddenTranslator()
        propose(
            client,
            action(
                "free",
                "a9_comms",
                "publish_alert",
                {
                    "area": "Ratnapura",
                    "event": "flood",
                    "instruction_text": "Use gate B",
                },
            ),
        )
        item = client.get("/approvals").json()[0]
        preview = client.get(f"/approvals/{item['id']}/preview").json()
        assert set(preview["missing"]) == {"si", "ta"}
        assert preview["texts"]["en"]["instruction"] == "Use gate B"
        assert client.get("/approvals/missing/preview").status_code == 404


def test_new_views_use_existing_read_permissions(monkeypatch):
    monkeypatch.setenv("ATLAS_TOKENS", json.dumps([{"token": "view", "role": "viewer"}]))
    with TestClient(create_app(Settings(database_path=":memory:"))) as client:
        propose(
            client,
            action("auth", "a9_comms", "publish_alert", {"area": "Ratnapura", "event": "flood"}),
        )
        headers = {"X-Operator-Token": "view"}
        aid = client.get("/approvals", headers=headers).json()[0]["id"]
        for path in ["/dev/sources", "/dev/operations/unknown", f"/approvals/{aid}/preview"]:
            assert client.get(path).status_code == 401
        assert client.get("/dev/sources", headers=headers).status_code == 200
        assert client.get(f"/approvals/{aid}/preview", headers=headers).status_code == 200
        assert (
            client.post(
                f"/approvals/{aid}/approve", headers=headers, json={"reviewer": "Viewer"}
            ).status_code
            == 403
        )
