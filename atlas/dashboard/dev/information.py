"""Read-only provenance and freshness labels. Confidence is never a truth label."""

import json
from datetime import datetime, timezone


def stamp(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


class Information:
    def __init__(self, runtime):
        self.runtime = runtime
        self.archived = not hasattr(runtime, "clock")
        if self.archived:
            row = runtime.db.connection.execute(
                "SELECT MAX(json_extract(body,'$.created_at')) FROM ledger WHERE kind='event'"
            ).fetchone()
            self.now = stamp(row[0]) if row[0] else datetime.now(timezone.utc)
        else:
            self.now = runtime.clock()
        self.freshness_seconds = (
            runtime.settings.sentinel.freshness_seconds if hasattr(runtime, "settings") else 300
        )
        self.evidence = {
            r["id"]: json.loads(r["body"])
            for r in runtime.db.connection.execute("SELECT id,body FROM evidence")
        }
        self.disputed = set()
        for row in runtime.db.connection.execute(
            "SELECT body FROM ledger WHERE kind='event' "
            "AND json_extract(body,'$.type')='conflict_flag'"
        ):
            self.disputed.update(json.loads(row[0])["payload"].get("evidence_ids", []))

    def describe(self, kind, *, refs=(), at=None, ttl=None, synthetic=False, note=None):
        labels = [kind, "synthetic", "replay"] if self.archived else [kind]
        ids = list(dict.fromkeys(refs))
        evidence = [self.evidence[r] for r in ids if r in self.evidence]
        times = [stamp(e.get("payload", {}).get("timestamp")) for e in evidence]
        times = [t for t in times if t is not None]
        observed = stamp(at) if at is not None else min(times, default=None)
        if ids and self.disputed.intersection(ids):
            labels.append("disputed")
        if observed and (self.now - observed).total_seconds() >= (
            ttl if ttl is not None else self.freshness_seconds
        ):
            labels.append("stale")
        replays = [e.get("payload", {}).get("_replay") for e in evidence]
        if any(e.get("source", "").startswith("sensor:open-meteo/") for e in evidence):
            labels[0] = "inferred"
            note = "Gridded weather reanalysis, not an on-site gauge measurement."
        if any(replays):
            note = (
                (note + " " if note else "")
                + "Historical or synthetic rehearsal input; values and time may be rescaled for the scenario."
            )
        if any(replays):
            labels.append("replay")
        if synthetic or any(r and r.get("synthetic") for r in replays):
            labels.append("synthetic")
        return {
            "labels": list(dict.fromkeys(labels)),
            "observed_at": observed.isoformat() if observed else None,
            "age_seconds": max(0, (self.now - observed).total_seconds()) if observed else None,
            "evidence_ids": [r for r in ids if r in self.evidence],
            "sources": sorted({e.get("source", "unknown") for e in evidence}),
            "note": note,
        }

    def event(self, event):
        kind = event["type"]
        payload = event.get("payload", {})
        base = (
            "observed"
            if kind in {"observation", "observation_validated", "mission_status", "alert_published"}
            else "inferred"
        )
        info = self.describe(
            base,
            refs=payload.get("evidence_ids", []),
            at=payload.get("observed_at") or payload.get("timestamp"),
        )
        if payload.get("_replay"):
            info["labels"].append("replay")
            if payload["_replay"].get("synthetic"):
                info["labels"].append("synthetic")
        # Derived events retain their root input's replay identity without changing contracts.
        roots = self.runtime.db.connection.execute(
            "WITH RECURSIVE ancestors(id) AS (SELECT ? UNION "
            "SELECT c.cause_id FROM event_causes c JOIN ancestors a ON c.event_id=a.id) "
            "SELECT body FROM ledger JOIN ancestors ON record_id='event:'||ancestors.id "
            "WHERE kind='event' AND json_extract(body,'$.payload._replay') IS NOT NULL",
            (event.get("id", ""),),
        )
        for row in roots:
            replay = json.loads(row[0])["payload"]["_replay"]
            info["labels"].append("replay")
            if replay.get("synthetic"):
                info["labels"].append("synthetic")
        if kind == "conflict_flag":
            info["labels"].append("disputed")
        info["labels"] = list(dict.fromkeys(info["labels"]))
        info["workflow"] = {
            "candidate_plan": "Candidate plan · not approved",
            "plan_proposed": "Proposed plan · not approval",
            "action_escalated": "Awaiting human approval",
            "action_authorised": "Authorised action · execution is a separate event",
            "action_blocked": "Blocked action",
            "alert_published": "Channel send recorded · recipient acknowledgement unavailable",
            "mission_status": f"Mission record · {payload.get('status', 'status update')}",
        }.get(kind)
        return info
