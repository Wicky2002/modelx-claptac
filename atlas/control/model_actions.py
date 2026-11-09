"""The Gateway's executor for model promotion and rollback.

Like A8 and A9 it is not a bus subscriber, so nothing reaches it without passing policy. The registry
makes its own check for a human approval, so a bug here cannot make an unapproved version live.
"""

from __future__ import annotations

from datetime import datetime, timezone

from atlas.control.models import ExecutionResult, Receipt
from atlas.core.events import ProposedAction
from atlas.learning.registry import ModelRegistry


class ModelActions:
    name = "model_registry"

    def __init__(self, registry: ModelRegistry, *, clock=None):
        self.registry = registry
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def execute(self, action: ProposedAction) -> ExecutionResult:
        name, target = action.params["name"], action.params["version"]
        current = self.registry.live(name)
        if current is None or current.version != target:  # already live: a resumed execution
            if action.action_type == "promote_model":
                self.registry.promote(name, target, actor=self.name)
            else:
                if self.registry.rollback_target(name) != target:
                    raise ValueError(f"{target} is not the rollback target for {name}")
                self.registry.rollback(name, actor=self.name)
        return ExecutionResult(
            receipt=Receipt(
                ref=f"{name}:{target}",
                executed_at=self.clock(),
                detail={"name": name, "version": target, "action": action.action_type},
            )
        )

    def verify(self, action: ProposedAction, result: ExecutionResult) -> bool:
        live = self.registry.live(action.params["name"])
        return live is not None and live.version == action.params["version"]

    def compensate(self, action: ProposedAction, result: ExecutionResult | None) -> None:
        """Nothing to undo: promote and rollback are single transactions that either happen or not."""
