"""S3's done-when: unapproved promotions are refused, and rollback works."""

import pytest

from atlas.control.models import DecisionStatus
from atlas.core.events import ProposedAction
from atlas.learning import FeatureSpec, ModelSpec, ModelStatus, RegistryError
from atlas.learning.registry import FeatureStats, promotion_key
from atlas.system import attach_all
from tests.control.conftest import fast_policy
from tests.model_helpers import promote_with_approval


@pytest.fixture
def system(runtime):
    return attach_all(runtime, policy=fast_policy())


def spec(version, stats=None):
    return ModelSpec(
        name="m",
        version=version,
        task="test",
        feature_schema={"x": FeatureSpec(type="float", nullable=True)},
        dataset_versions={"d": "1"},
        metrics={"f1": 0.5},
        operating_threshold=0.5,
        feature_stats=stats or {},
    )


def add_live(runtime, version="v1", stats=None, value=0.1):
    runtime.models.register(spec(version, stats))
    promote_with_approval(runtime, "m", version)
    runtime.inference.bind("m", version, lambda f: {"score": value})


def add_shadow(runtime, version="v2", value=0.3):
    runtime.models.register(spec(version))
    runtime.models.set_status("m", version, ModelStatus.SHADOW, actor="test")
    runtime.inference.bind("m", version, lambda f: {"score": value})


def ask(runtime, n=1, x=1.0):
    return [runtime.inference.predict("m", {"x": x}, caller="test") for _ in range(n)]


def live_version(runtime):
    return runtime.models.live("m").version


def pending(system):
    return system.control.approvals.pending()


async def requested_promotion(runtime, system):
    add_live(runtime)
    add_shadow(runtime)
    ask(runtime)
    assert (await system.learning.request_promotion("m", "v2"))["requested"]
    (item,) = pending(system)
    return item


# ------------------------------------------------------------------- promotion


async def test_a_request_waits_for_a_human_and_changes_nothing(runtime, system):
    await requested_promotion(runtime, system)
    await system.control.gateway.run_pending()
    assert live_version(runtime) == "v1"
    assert runtime.models.get("m", "v2").status is ModelStatus.SHADOW


async def test_human_approval_promotes_and_rollback_restores(runtime, system):
    item = await requested_promotion(runtime, system)
    gateway = system.control.gateway
    gateway.approve(item.id, "commander")
    await gateway.run_pending()
    assert live_version(runtime) == "v2"
    assert runtime.models.get("m", "v1").status is ModelStatus.RETIRED

    assert (await system.learning.request_rollback("m", "worse in the field"))["requested"]
    await gateway.run_pending()
    assert live_version(runtime) == "v2"  # a rollback needs a human too
    (rollback,) = pending(system)
    gateway.approve(rollback.id, "commander")
    await gateway.run_pending()
    assert live_version(runtime) == "v1"
    assert runtime.models.get("m", "v2").status is ModelStatus.RETIRED
    assert runtime.ledger.verify()


async def test_rollback_is_one_step(runtime, system):
    item = await requested_promotion(runtime, system)
    gateway = system.control.gateway
    gateway.approve(item.id, "commander")
    await gateway.run_pending()
    await system.learning.request_rollback("m")
    gateway.approve(pending(system)[0].id, "commander")
    await gateway.run_pending()
    assert await system.learning.request_rollback("m") == {
        "requested": False,
        "reason": "nothing_to_roll_back_to",
    }


async def test_rejected_promotion_stays_in_shadow(runtime, system):
    item = await requested_promotion(runtime, system)
    system.control.gateway.reject(item.id, "commander", "not convinced")
    await system.control.gateway.run_pending()
    assert live_version(runtime) == "v1"


async def test_no_shadow_results_means_no_request(runtime, system):
    add_live(runtime)
    add_shadow(runtime)
    result = await system.learning.request_promotion("m", "v2")
    assert result == {"requested": False, "reason": "no_shadow_results"}
    assert not pending(system)


# --------------------------------------------------------------------- attacks


def test_attack_calling_the_registry_directly_is_refused(runtime):
    add_live(runtime)
    add_shadow(runtime)
    with pytest.raises(RegistryError):
        runtime.models.promote("m", "v2", actor="attacker")
    with pytest.raises(RegistryError):
        runtime.models.set_status("m", "v2", ModelStatus.LIVE, actor="attacker")
    with pytest.raises(RegistryError):
        runtime.models.set_status("m", "v1", ModelStatus.RETIRED, actor="attacker")
    assert live_version(runtime) == "v1"


def test_attack_rollback_without_approval_is_refused(runtime):
    add_live(runtime)
    runtime.models.register(spec("v2"))
    promote_with_approval(runtime, "m", "v2")
    with pytest.raises(RegistryError):
        runtime.models.rollback("m", actor="attacker")
    assert live_version(runtime) == "v2"


def test_attack_an_approval_for_one_version_does_not_cover_another(runtime):
    add_live(runtime)
    add_shadow(runtime, "v2")
    add_shadow(runtime, "v3")
    runtime.ledger.append(f"action:{promotion_key('m', 'v2')}:approved", "action", {"phase": "x"})
    with pytest.raises(RegistryError):
        runtime.models.promote("m", "v3", actor="attacker")
    assert live_version(runtime) == "v1"


async def test_attack_a_reviewer_edit_cannot_swap_in_another_version(runtime, system):
    item = await requested_promotion(runtime, system)
    add_shadow(runtime, "v3")
    gateway = system.control.gateway
    gateway.edit(item.id, "commander", {"name": "m", "version": "v3"})
    await gateway.run_pending()
    assert live_version(runtime) == "v1"
    assert gateway.get(item.idempotency_key).status is DecisionStatus.COMPENSATED


async def test_attack_loosened_policy_still_cannot_go_live(runtime):
    """Even if someone marks promotion low-consequence, the registry wants a human approval."""
    from atlas.control.policy_engine import Policy, PolicyEngine

    data = Policy.load().model_dump()
    data["actions"]["promote_model"] = {
        "consequence": "low",
        "when": {},
        "proposers": ["a10_data_learning"],
    }
    data["gateway"]["retry_backoff_seconds"] = 0
    system = attach_all(runtime, policy=PolicyEngine(Policy.model_validate(data)))
    add_live(runtime)
    add_shadow(runtime)
    ask(runtime)
    await system.learning.request_promotion("m", "v2")
    await system.control.gateway.run_pending()
    assert live_version(runtime) == "v1"


@pytest.mark.parametrize(
    "executor, action_type, params",
    [
        ("a9_comms", "publish_alert", {"scope": "local", "instruction": "avoid_area"}),
        ("a8_dispatch", "update_mission", {"mission_id": "x"}),
        ("a8_dispatch", "close_major_route", {"road_id": "x"}),
    ],
)
def test_attack_a10_cannot_propose_anything_else(system, executor, action_type, params):
    decision = system.control.gateway.submit(
        ProposedAction(
            idempotency_key="k",
            incident_id="i",
            proposed_by="a10_data_learning",
            executor=executor,
            action_type=action_type,
            params=params,
        )
    )
    assert decision.reason == "unauthorised_proposer"


def test_a10_holds_nothing_that_can_write(system):
    a10 = system.learning
    for view in (a10.registry, a10.ledger):
        for forbidden in ("promote", "rollback", "set_status", "register", "append", "db"):
            assert not hasattr(view, forbidden)


# ---------------------------------------------------------------- drift, shadow


STATS = {"x": FeatureStats(mean=1.0, std=1.0)}


def test_shadow_runs_beside_live_and_never_answers(runtime):
    add_live(runtime, value=0.1)
    add_shadow(runtime, value=0.3)
    (result,) = ask(runtime)
    assert result.output == {"score": 0.1} and result.version == "v1"
    (shadow,) = [r["payload"] for r in runtime.ledger.records("shadow_prediction")]
    assert shadow["shadow_of"] == result.prediction_id and shadow["output"] == {"score": 0.3}


def test_shadow_summary_compares_with_live(system, runtime):
    add_live(runtime, value=0.1)
    add_shadow(runtime, value=0.3)
    ask(runtime, 3, x=1.0)
    ask(runtime, 1, x=2.0)
    summary = system.learning.shadow_summary("m", "v2")
    assert summary["compared_with_live"] >= 1 and summary["errors"] == 0
    assert summary["mean_abs_difference"] == pytest.approx(0.2)


def test_a_failing_shadow_cannot_affect_the_live_answer(runtime, system):
    add_live(runtime)
    add_shadow(runtime)

    def broken(_):
        raise RuntimeError

    runtime.inference.bind("m", "v2", broken)
    (result,) = ask(runtime)
    assert result.usable
    assert system.learning.shadow_summary("m", "v2")["errors"] == 1


def distinct(runtime, count, x):
    """Advance the clock so each call is its own ledger record."""
    from datetime import timedelta

    for _ in range(count):
        runtime.clock.now += timedelta(seconds=1)
        ask(runtime, x=x)


def test_drift_is_found_and_too_little_data_is_not_called_clean(runtime, system):
    add_live(runtime, stats=STATS)
    distinct(runtime, 5, 1.0)
    report = system.learning.drift("m")
    assert report["status"] == "insufficient_data" and report["drifted"] is None
    distinct(runtime, 30, 3.0)
    report = system.learning.drift("m")
    assert report["status"] == "checked" and report["drifted"] is True


def test_matching_inputs_are_not_flagged(runtime, system):
    add_live(runtime, stats=STATS)
    distinct(runtime, 35, 1.0)
    report = system.learning.drift("m")
    assert report["drifted"] is False and report["features"]["x"]["shift_std"] == 0


def test_a_jump_in_missing_values_is_drift(runtime, system):
    add_live(runtime, stats=STATS)
    distinct(runtime, 35, None)
    assert system.learning.drift("m")["features"]["x"]["drifted"] is True


def test_drift_without_a_reference_says_so(runtime, system):
    add_live(runtime)
    assert system.learning.drift("m")["status"] == "no_reference"


async def test_review_goes_on_the_ledger_and_changes_no_model(runtime, system):
    add_live(runtime)
    add_shadow(runtime)
    ask(runtime)
    before = [m.model_dump() for m in runtime.models.list()]
    await system.learning.review("m")
    assert any(
        r["payload"]["type"] == "model_review" for r in runtime.ledger.records("event")
    )
    assert [m.model_dump() for m in runtime.models.list()] == before
