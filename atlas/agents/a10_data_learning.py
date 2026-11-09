"""Agent 10 - Data & Learning: watches the models and asks a human to change them.

It reads the registry and ledger through views with no write methods, and its only output is events.
It cannot change a live threshold, the policy, model weights or the ledger (§6, §7.1). Promotion and
rollback are requests to the Gateway, which always sends them to a human.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from hashlib import sha256

from atlas.core.events import Event, EventType, ProposedAction
from atlas.learning.registry import ModelStatus, promotion_key, rollback_key

NAME = "a10_data_learning"
EXECUTOR = "model_registry"
DRIFT_SHIFT = 0.5  # standard deviations of training data; a review prompt, not a calibrated test
DRIFT_MISSING = 0.2  # change in the share of missing values
MIN_SAMPLES = 30
WINDOW = 500


class RegistryView:
    """The read side of ModelRegistry."""

    def __init__(self, registry):
        self.get, self.live, self.list = registry.get, registry.live, registry.list
        self.rollback_target = registry.rollback_target


class LedgerView:
    """The read side of Ledger."""

    def __init__(self, ledger):
        self.records = ledger.records


def _numbers(value, path="") -> dict[str, float]:
    if isinstance(value, dict):
        return {k: v for key, item in value.items() for k, v in _numbers(item, f"{path}/{key}").items()}
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return {path: float(value)}
    return {}


class DataLearning:
    name = NAME

    def __init__(self, registry: RegistryView, ledger: LedgerView, publish, *, clock=None):
        self.registry, self.ledger, self._publish = registry, ledger, publish
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------- drift

    def drift(self, name: str) -> dict:
        """Compare what the live model has been receiving with its training distribution."""
        live = self.registry.live(name)
        if live is None:
            return {"model": name, "status": "no_live_model", "drifted": None}
        result = {"model": name, "version": live.version}
        if not live.feature_stats:
            return {**result, "status": "no_reference", "drifted": None}
        rows = [
            r["payload"]["features"]
            for r in self.ledger.records("prediction")
            if r["payload"]["model"] == name
            and r["payload"]["version"] == live.version
            and r["payload"]["status"] == "ok"
        ][-WINDOW:]
        if len(rows) < MIN_SAMPLES:
            # Too few to say. This is deliberately not reported as "no drift".
            return {**result, "status": "insufficient_data", "samples": len(rows), "drifted": None}
        features = {}
        for feature, reference in live.feature_stats.items():
            values = [row[feature] for row in rows if row.get(feature) is not None]
            missing = 1 - len(values) / len(rows)
            numeric = [v for v in values if isinstance(v, (int, float))]
            shift = (
                abs(sum(numeric) / len(numeric) - reference.mean) / reference.std
                if numeric
                else None
            )
            features[feature] = {
                "shift_std": round(shift, 4) if shift is not None else None,
                "missing_rate": round(missing, 4),
                "drifted": (shift is not None and shift >= DRIFT_SHIFT)
                or abs(missing - reference.missing_rate) >= DRIFT_MISSING,
            }
        return {
            **result,
            "status": "checked",
            "samples": len(rows),
            "features": features,
            "drifted": any(f["drifted"] for f in features.values()),
        }

    # ------------------------------------------------------------------ shadow

    def shadow_summary(self, name: str, version: str) -> dict:
        """How a shadow version compared with the live model on the same inputs."""
        live_outputs = {
            r["payload"]["prediction_id"]: r["payload"]["output"]
            for r in self.ledger.records("prediction")
            if r["payload"]["model"] == name and r["payload"]["status"] == "ok"
        }
        runs = errors = compared = 0
        differences: list[float] = []
        for record in self.ledger.records("shadow_prediction"):
            payload = record["payload"]
            if payload["model"] != name or payload["version"] != version:
                continue
            runs += 1
            if payload["status"] != "ok":
                errors += 1
                continue
            live = live_outputs.get(payload["shadow_of"])
            if live is None:
                continue
            compared += 1
            ours, theirs = _numbers(payload["output"]), _numbers(live)
            differences += [abs(ours[key] - theirs[key]) for key in ours.keys() & theirs.keys()]
        return {
            "model": name,
            "version": version,
            "runs": runs,
            "errors": errors,
            "compared_with_live": compared,
            "mean_abs_difference": round(sum(differences) / len(differences), 4)
            if differences
            else None,
        }

    # ------------------------------------------------------------------ output

    async def review(self, name: str) -> dict:
        """Publish the current drift and shadow picture for one model."""
        report = {
            "model": name,
            "drift": self.drift(name),
            "shadow": [
                self.shadow_summary(name, m.version)
                for m in self.registry.list(name)
                if m.status is ModelStatus.SHADOW
            ],
        }
        now = self.clock()
        await self._publish(
            Event(
                id=sha256(f"model_review:{name}:{now.isoformat()}".encode()).hexdigest(),
                type=EventType.MODEL_REVIEW,
                source=NAME,
                created_at=now,
                payload=report,
            )
        )
        return report

    async def request_promotion(self, name: str, version: str) -> dict:
        """Ask for a shadow version to go live. A human decides; nothing changes here."""
        record = self.registry.get(name, version)
        if record is None or record.status is not ModelStatus.SHADOW:
            return {"requested": False, "reason": "not_in_shadow"}
        summary = self.shadow_summary(name, version)
        if summary["runs"] == 0:
            return {"requested": False, "reason": "no_shadow_results"}
        key = promotion_key(name, version)
        rationale = f"Shadow results: {summary}. Test metrics: {record.metrics}."
        await self._propose("promote_model", key, name, version, rationale)
        return {"requested": True, "idempotency_key": key}

    async def request_rollback(self, name: str, reason: str = "") -> dict:
        """Ask to restore the version the last promotion replaced."""
        live, target = self.registry.live(name), self.registry.rollback_target(name)
        if live is None or target is None:
            return {"requested": False, "reason": "nothing_to_roll_back_to"}
        key = rollback_key(name, live.version, target)
        await self._propose("rollback_model", key, name, target, reason or "Rollback requested")
        return {"requested": True, "idempotency_key": key}

    async def _propose(self, action_type, key, name, version, rationale) -> None:
        action = ProposedAction(
            id=sha256(key.encode()).hexdigest(),
            idempotency_key=key,
            incident_id=f"model:{name}",
            proposed_by=NAME,
            executor=EXECUTOR,
            action_type=action_type,
            params={"name": name, "version": version},
            rationale=rationale,
        )
        await self._publish(
            Event(
                id=sha256(f"plan:{key}".encode()).hexdigest(),
                type=EventType.PLAN_PROPOSED,
                source=NAME,
                incident_id=action.incident_id,
                created_at=self.clock(),
                payload={"actions": [action.model_dump(mode="json")]},
            )
        )
