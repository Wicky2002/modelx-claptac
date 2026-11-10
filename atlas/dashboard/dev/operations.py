"""Read-only operational views of recorded source and planning state."""

import json
from hashlib import sha256

from atlas.dashboard.dev.information import Information, stamp
from atlas.dashboard.dev.trace import summarise
from atlas.memory.ledger import canonical


def _events(runtime):
    return [
        json.loads(r[0])
        for r in runtime.db.connection.execute(
            "SELECT body FROM ledger WHERE kind='event' ORDER BY seq"
        )
    ]


def source_health(runtime):
    info = Information(runtime)
    sources = {}
    events = _events(runtime)
    accepted = {}
    outcomes = {}
    for event in events:
        p = event["payload"]
        if event["type"] == "observation_validated":
            # The first evidence ID is this input; later IDs are corroborating peers.
            refs = p.get("evidence_ids", [])
            if refs:
                accepted[refs[0]] = p.get("received_at", event["created_at"])
                outcomes[refs[0]] = "accepted"
        elif event["type"] == "observation_rejected":
            for ref in p.get("evidence_ids", []):
                outcomes[ref] = p.get("reason", "rejected")
    for event in events:
        if event["type"] != "observation":
            continue
        p = event["payload"]
        ref = sha256(canonical({"source": event["source"], "payload": p}).encode()).hexdigest()
        key = (event["source"], p.get("type") or p.get("attribute") or "report")
        previous = sources.get(key, {})
        try:
            observed = stamp(p.get("timestamp"))
            if observed and observed.tzinfo is None:
                observed = None
        except (TypeError, ValueError, OverflowError):
            observed = None
        # A poll that succeeded without an observation cannot be inferred from the ledger.
        sources[key] = {
            "source": key[0],
            "attribute": key[1],
            "observed_at": observed.isoformat() if observed else None,
            "arrived_at": event["created_at"],
            "last_accepted_at": accepted.get(ref, previous.get("last_accepted_at")),
            "last_successful_refresh": None,
            "refresh_note": "Adapter fetch status is not recorded; arrival and accepted ingest are shown separately.",
            "age_seconds": max(0, (info.now - observed).total_seconds()) if observed else None,
            "value": p.get("value"),
            "unit": p.get("unit"),
            "status": outcomes.get(ref, "awaiting_validation"),
            "information": info.describe("observed", refs=[ref]) if observed else None,
        }
    return {"as_of": info.now.isoformat(), "sources": list(sources.values())}


def incident_operations(system, incident_id):
    runtime = system.runtime
    state = system.orchestration.commander.get_incident(incident_id)
    if state is None:
        return None
    info = Information(runtime)
    area = state.get("area_id")
    events = _events(runtime)
    changes = []
    conflicts = []
    for event in events:
        p = event["payload"]
        if event["type"] == "conflict_flag" and p.get("area_id") == area:
            conflicts.append(
                {
                    "at": event["created_at"],
                    "attribute": p.get("attribute"),
                    "reports": [
                        {
                            "id": ref,
                            **info.evidence[ref],
                            "information": info.describe("observed", refs=[ref]),
                        }
                        for ref in p.get("evidence_ids", [])
                        if ref in info.evidence
                    ],
                }
            )
        if event.get("incident_id") == incident_id and event["type"] in {
            "trigger",
            "risk_update",
            "plan_proposed",
            "action_escalated",
            "action_blocked",
            "action_authorised",
            "mission_status",
        }:
            changes.append(event)
    plans = state.get("plans", {})
    routing = plans.get("a4_evacuation")
    shelter = plans.get("a7_shelter")
    logistics = [
        {"planner": name, **plan} for name, plan in plans.items() if name.startswith("a6_logistics")
    ]
    return {
        "incident_id": incident_id,
        "area_id": area,
        "hazard": state.get("hazard"),
        "level": state.get("level"),
        "state": state.get("state"),
        "updated_at": state.get("updated_at"),
        "cycle": state.get("cycle"),
        "summary": state.get("summary"),
        "needs_human": state.get("needs_human"),
        "notes": state.get("notes", []),
        "changes": [
            {
                "id": e["id"],
                "at": e["created_at"],
                "type": e["type"],
                "summary": summarise(e),
                "information": info.event(e),
            }
            for e in changes[-30:][::-1]
        ],
        "conflicts": conflicts[-10:][::-1],
        "route_plan": {**routing, "options": routing.get("options", [])} if routing else None,
        "shelter_plan": {**shelter, "unplaced": shelter.get("unplaced", [])} if shelter else None,
        "logistics_plans": logistics,
        "approvals": [
            a.model_dump(mode="json")
            for a in system.control.approvals.pending()
            if a.incident_id == incident_id
        ],
        "planning_note": "Candidate plans are not approved missions. Capacities and fleet use synthetic reference data; plan shortages are not a field inventory.",
    }
