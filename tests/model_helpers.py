from atlas.learning import ModelStatus
from atlas.learning.registry import promotion_key


def promote_with_approval(runtime, name, version):
    """Make a registered candidate live, standing in for the Gateway's record of a human approval."""
    runtime.models.set_status(name, version, ModelStatus.SHADOW, actor="test")
    key = promotion_key(name, version)
    runtime.ledger.append(f"action:{key}:approved", "action", {"phase": "approved"})
    runtime.models.promote(name, version, actor="test")
