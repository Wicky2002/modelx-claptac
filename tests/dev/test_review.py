"""Report provenance, absent dependencies, strict reads and S1/S3 integration."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from atlas.dashboard.dev.review import (
    Profile,
    data_exploration,
    model_review,
    read_file,
)
from tests.manager.conftest import as_, secured  # noqa: F401


@pytest.fixture
def reports(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_REVIEW_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("ATLAS_REVIEW_REPORTS_DIR", str(tmp_path))
    return tmp_path


def write_reports(root, profile=None, report=None):
    index = {"schema_version": 1, "profiles": [], "evaluations": []}
    if profile is not None:
        (root / "profile.json").write_text(json.dumps(profile))
        index["profiles"].append("profile.json")
    if report is not None:
        (root / "report_test.json").write_text(json.dumps(report))
        index["evaluations"].append(
            {"path": "report_test.json", "dataset": "mmflood", "source": "Test fixture"}
        )
    (root / "index.json").write_text(json.dumps(index))


def test_default_is_recorded_and_missing_is_not_sample(reports):
    result = data_exploration()
    assert result["mode"] == "recorded"
    assert result["profiles"] == result["evaluations"] == result["cards"] == []
    samples = data_exploration(sample=True)
    assert samples["mode"] == "sample"
    for profile in samples["profiles"]:
        Profile.model_validate(profile)


def test_profile_counts_and_provenance_survive_without_guessing(reports):
    profile = deepcopy(data_exploration(sample=True)["profiles"][0])
    profile.update(dataset_version=None, seed=None)
    write_reports(reports, profile=profile)
    result = data_exploration()
    assert not result["warnings"]
    p = result["profiles"][0]
    assert p["dataset_version"] is p["seed"] is None
    assert p["flood_pixels"] == {"flood": 3000, "non_flood": 97000, "ignored": 2500}


@pytest.mark.parametrize("bad", [-1, 1.5, True, "12"])
def test_invalid_pixel_counts_do_not_reach_chart(reports, bad):
    profile = deepcopy(data_exploration(sample=True)["profiles"][0])
    profile["flood_pixels"]["flood"] = bad
    write_reports(reports, profile=profile)
    result = data_exploration()
    assert not result["profiles"] and result["warnings"]


def test_relationship_denominator_and_finite_coordinates():
    profile = deepcopy(data_exploration(sample=True)["profiles"][2])
    profile["relationships"][0]["total_pairs"] += 1
    with pytest.raises(ValidationError):
        Profile.model_validate(profile)
    profile["relationships"][0]["total_pairs"] -= 1
    profile["relationships"][0]["bins"][0]["x"] = float("nan")
    with pytest.raises(ValidationError):
        Profile.model_validate(profile)


def test_native_d2_reports_keep_undefined_scores_and_missing_metadata(reports):
    report = {
        "split": "test",
        "tiles": 7,
        "combined": {
            "all_pixels": {
                "iou": float("nan"),
                "f1": 0,
                "precision": 0.7,
                "recall": 0,
                "threshold": 0.45,
            },
            "mean_event_iou": 0.2,
            "mean_event_f1": 0.3,
            "events": 2,
        },
    }
    write_reports(reports, report=report)
    result = data_exploration()
    assert not result["warnings"]
    evaluation = result["evaluations"][0]
    assert evaluation["seed"] is evaluation["dataset_version"] is None
    assert evaluation["model_version"] is evaluation["generated_at"] is None
    assert evaluation["split"] == "test" and evaluation["tiles"] == 7
    assert evaluation["variants"][0]["metrics"]["iou"] is None
    assert evaluation["variants"][0]["metrics"]["f1"] == 0
    report["combined"]["all_pixels"]["f1"] = 1.5
    write_reports(reports, report=report)
    assert data_exploration()["warnings"]


def test_bad_manifest_and_individual_report_are_visible(reports):
    (reports / "index.json").write_text("broken")
    assert "index.json" in data_exploration()["warnings"][0]
    write_reports(reports, profile=data_exploration(sample=True)["profiles"][0], report=[])
    result = data_exploration()
    assert len(result["profiles"]) == 1 and len(result["warnings"]) == 1


def test_paths_cannot_escape_through_parent_absolute_or_symlink(reports):
    outside = reports.parent / "outside-u4.json"
    outside.write_text("{}")
    (reports / "link.json").symlink_to(outside)
    for name in ("../outside-u4.json", str(outside), "link.json"):
        with pytest.raises(ValueError):
            read_file(reports, name)
    (reports / "large.json").write_bytes(b" " * 5_000_001)
    with pytest.raises(ValueError):
        read_file(reports, "large.json")


def test_model_reads_use_only_summary_methods_and_do_not_change_ledger(system):
    rows = model_review(system, sample=True)["models"]
    registry = Mock()
    registry.list.return_value = [SimpleNamespace(model_dump=lambda mode, row=r: row) for r in rows]
    learning = Mock()
    learning.drift.return_value = {"status": "insufficient_data", "samples": 0, "drifted": None}
    learning.shadow_summary.return_value = {"runs": 0, "mean_abs_difference": None}
    system.runtime.models = registry
    system.learning = learning
    before = system.runtime.ledger.records()
    result = model_review(system)
    assert result["reviews"][0]["drift"]["drifted"] is None
    assert result["reviews"][0]["shadows"][0]["mean_abs_difference"] is None
    learning.review.assert_not_called()
    assert system.runtime.ledger.records() == before
    assert system.runtime.ledger.verify()


@pytest.mark.parametrize("path", ["/dev/data-exploration", "/dev/model-review"])
def test_review_routes_obey_read_permissions_and_samples_do_not_write(secured, path):  # noqa: F811
    before = secured.app.state.runtime.ledger.records()
    assert secured.get(path).status_code == 401
    for suffix in ("", "?sample=true"):
        response = secured.get(path + suffix, headers=as_("view"))
        assert response.status_code == 200
        assert response.json()["mode"] == ("sample" if suffix else "recorded")
    assert secured.app.state.runtime.ledger.records() == before
    assert secured.post(path, headers=as_("view")).status_code == 405


async def test_real_s1_s3_promote_drift_shadow_and_rollback(system):
    """Runs when the upstream learning branch is present; no substitute registry."""
    pytest.importorskip("atlas.learning")
    from atlas.learning.registry import FeatureStats
    from tests.learning.test_a10_data_learning import add_live, add_shadow, distinct

    runtime = system.runtime
    add_live(runtime, stats={"x": FeatureStats(mean=0, std=1)})
    add_shadow(runtime)
    distinct(runtime, 35, 1.0)
    before = runtime.ledger.records()
    result = model_review(system)
    review = next(r for r in result["reviews"] if r["name"] == "m")
    assert review["drift"]["drifted"] is True
    assert review["shadows"][0]["compared_with_live"] == 35
    assert runtime.ledger.records() == before
    await system.learning.request_promotion("m", "v2")
    result = model_review(system)
    assert result["requests"][0]["action"]["action_type"] == "promote_model"
    pending = system.control.approvals.pending()[0]
    system.control.gateway.approve(pending.id, "test-commander")
    await system.control.gateway.run_pending()
    await system.learning.request_rollback("m", "test rollback")
    pending = system.control.approvals.pending()[0]
    system.control.gateway.approve(pending.id, "test-commander")
    await system.control.gateway.run_pending()
    result = model_review(system)
    assert next(m for m in result["models"] if m["status"] == "live" and m["name"] == "m")["version"] == "v1"
    assert any(h.get("to") == "live" and h["version"] == "v1" for h in result["history"])
    assert {r["action"]["action_type"] for r in result["requests"]} == {
        "promote_model",
        "rollback_model",
    }
    assert runtime.ledger.verify()
