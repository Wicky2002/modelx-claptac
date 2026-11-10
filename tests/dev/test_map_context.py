from atlas.core.events import Belief
from atlas.dashboard.dev.geo_view import situation_map
from tests.dev.test_trace import loop


async def test_routes_link_incident_destination_and_source_evidence(system, runtime, clock):
    await loop(system, runtime, clock)
    view = situation_map(system)
    # This fixture's tiny road graph has no area-to-edge mapping. Link a real
    # fixture observation to one traversed edge to exercise source propagation.
    evidence = runtime.db.connection.execute("SELECT id FROM evidence LIMIT 1").fetchone()[0]
    edge = view["routes"][0]["road_ids"][0]
    runtime.cop.put(
        Belief(
            subject=f"edge:{edge}",
            attribute="belief_open",
            value=0.6,
            confidence=0.7,
            provenance=[evidence],
            updated_at=clock(),
        )
    )
    view = situation_map(system)
    assert view["flood_extents"] == []  # An inferred radius is never published as flood geometry.
    assert view["routes"]
    assert any(r["information"]["evidence_ids"] for r in view["routes"])
    shelters = {s["id"]: s for s in view["shelters"]}
    for route in view["routes"]:
        assert route["incident_id"]
        assert route["road_ids"]
        if route["destination_id"]:
            assert set(route["information"]["evidence_ids"]) <= set(
                shelters[route["destination_id"]]["approach_evidence_ids"]
            )


def test_source_flood_geometry_is_validated_and_not_confused_with_area_radius(
    system, runtime, clock
):
    polygon = {
        "type": "Polygon",
        "coordinates": [[[80.4, 6.7], [80.41, 6.7], [80.41, 6.71], [80.4, 6.7]]],
    }
    for subject, value in [
        ("area:valid", polygon),
        ("area:bad", {"type": "Polygon", "coordinates": [[]]}),
    ]:
        runtime.cop.put(
            Belief(
                subject=subject,
                attribute="flood_extent",
                value=value,
                confidence=0.7,
                provenance=[],
                updated_at=clock(),
            )
        )
    extents = situation_map(system)["flood_extents"]
    assert len(extents) == 1
    assert extents[0]["geometry"] == polygon
    assert "inferred" in extents[0]["information"]["labels"]
