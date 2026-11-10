"""A captured bench run can be validated and replayed through A1."""

import importlib
import json
from pathlib import Path

import pytest

from atlas.datasets.bench_recording import build_bench_scenario, load_recordings
from atlas.ingest.simulator import replay
from tests.conftest import events


def reading(node, kind, value, unit, second):
    return {
        "node_id": node,
        "sensor_id": kind,
        "measurement_id": f"{node}-{kind}-{second}",
        "type": kind,
        "value": value,
        "unit": unit,
        "timestamp": f"2026-11-09T10:00:{second:02d}+00:00",
        "location": {"lat": 6.6828, "lon": 80.3992, "area_id": "ratnapura-demo-river"},
    }


async def test_recorded_nodes_convert_and_trigger_a1(tmp_path, runtime, clock, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "hardware" / "pi"))
    node = importlib.import_module("sensor_node")
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    for item in [
        reading("first", "water_level", 30, "cm", 0),
        reading("first", "soil_moisture", 90, "%", 10),
    ]:
        node.record_reading(str(first), item)
    node.record_reading(str(second), reading("second", "tilt", 3.0, "deg", 20))

    captured = load_recordings([first, second])
    scenario = build_bench_scenario(captured, "bench-test")
    assert scenario["recording_kind"] == "bench_test" and scenario["real"] is False
    assert scenario["observed_ranges"]["tilt (deg)"] == {"min": 3.0, "max": 3.0}
    assert [event["at_seconds"] for event in scenario["events"]] == [0, 10, 20]
    await runtime.start()
    await replay(runtime, scenario, clock)
    assert events(runtime, "trigger")
    await runtime.close()


def test_bad_or_incomplete_recording_is_rejected(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(reading("one", "tilt", 3, "cm", 0)) + "\n")
    with pytest.raises(ValueError, match="invalid sensor reading"):
        load_recordings([path])
    path.write_text(json.dumps(reading("one", "tilt", 3, "deg", 0)) + "\n")
    with pytest.raises(ValueError, match="missing: soil_moisture, water_level"):
        build_bench_scenario(load_recordings([path]), "bench-test")
