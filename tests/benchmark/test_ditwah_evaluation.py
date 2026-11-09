import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas.benchmark import ditwah
from atlas.benchmark.runner import run_case
from atlas.benchmark.schema import load_tasks
from atlas.learning import FeatureSpec, ModelSpec
from atlas.learning.cards import main as cards_main
from atlas.learning.cards import model_card

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def scenario():
    return ditwah.load()


def test_strict_mode_has_no_reanalysis(scenario):
    entries = ditwah.entries_for(scenario, "strict")
    assert entries and not any(ditwah.is_reanalysis(e) for e in entries)
    assert any(ditwah.is_reanalysis(e) for e in ditwah.entries_for(scenario, "assisted"))


def test_strict_mode_runs_at_real_speed(scenario):
    entries = ditwah.entries_for(scenario, "strict")
    span = entries[-1]["at_seconds"] - entries[0]["at_seconds"]
    assert 40 * 3600 < span < 60 * 3600  # days, not the demo's 16 minutes


def test_times_come_from_the_gauge_not_the_local_time_label(scenario):
    assert ditwah.origin_of(scenario) == datetime(2025, 11, 26, 18, 42, 31, tzinfo=timezone.utc)


def test_scenario_carries_the_checked_anchors(scenario):
    anchors = ditwah.anchors(scenario)
    assert anchors["peak_m"] == 10.21
    assert anchors["major_crossing_utc"].startswith("2025-11-28T06:32:58")


async def test_strict_replay_warns_before_major_flood_without_future_data(scenario):
    result = await ditwah.run_mode(scenario, "strict")
    assert result["first_trigger_reason"] == "water_level"
    assert result["lead_hours_before_major"] == pytest.approx(21.96, abs=0.01)


def test_unknown_mode_is_refused(scenario):
    with pytest.raises(ValueError):
        ditwah.entries_for(scenario, "best_case")


async def test_the_model_task_really_calls_the_stand_in_classifier(tmp_path):
    (task,) = load_tasks(ROOT / "data/benchmarks/model-tasks")
    result = await run_case(task, 42, tmp_path / "case", stand_in_models=True)
    assert result["passed"], result["checks"]
    records = [json.loads(line) for line in (tmp_path / "case" / "ledger.jsonl").open()]
    predictions = [r["payload"] for r in records if r["kind"] == "prediction"]
    assert [(p["model"], p["status"]) for p in predictions] == [("report_classifier", "ok")]


def spec():
    return ModelSpec(
        name="radar_flood",
        version="v1",
        task="flood segmentation",
        feature_schema={"a": FeatureSpec(type="float", nullable=True)},
        dataset_versions={"mmflood": "1.0"},
        metrics={"iou": 0.61},
        operating_threshold=0.42,
        artifact_uri="drive://weights",
    )


def test_model_card_states_what_the_registry_holds(runtime):
    card = model_card(runtime.models.register(spec()))
    for expected in ("radar_flood v1", "`mmflood`: 1.0", "`iou`: 0.61", "0.42", "candidate", "drive://"):
        assert expected in card


def test_cards_command_writes_one_file_per_version(tmp_path):
    from atlas.core.storage import Database
    from atlas.learning import ModelRegistry
    from atlas.memory.ledger import Ledger

    path = tmp_path / "atlas.db"
    db = Database(str(path))
    ModelRegistry(db, Ledger(db)).register(spec())
    db.close()
    assert cards_main(["--database", str(path), "--out", str(tmp_path / "cards")]) == 0
    assert (tmp_path / "cards" / "radar_flood-v1.md").exists()
