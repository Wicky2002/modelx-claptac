"""The committed simulated bench data is reproducible and exercises A1."""

import json
from pathlib import Path

from atlas.datasets.simulated_bench import build_scenario
from atlas.ingest.sensors import SensorReading
from atlas.ingest.simulator import replay
from tests.conftest import events

SCENARIO = Path(__file__).resolve().parents[2] / "data/scenarios/ratnapura_simulated_bench.json"


async def test_simulated_bench_replays_water_soil_and_tilt(runtime, clock):
    scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))
    assert scenario == build_scenario()
    assert scenario["real"] is False
    assert scenario["recording_kind"] == "simulated_bench"
    assert len(scenario["events"]) == 183

    series = {kind: [] for kind in ("water_level", "soil_moisture", "tilt")}
    for entry in scenario["events"]:
        payload = entry["payload"]
        SensorReading.model_validate({**payload, "timestamp": "2026-11-10T09:00:00+00:00"})
        series[payload["type"]].append((entry["at_seconds"], payload["value"]))
    for samples in series.values():
        assert [offset for offset, _ in samples] == list(range(0, 601, 10))
    assert max(value for _, value in series["water_level"]) < 40
    assert series["water_level"][0][1] < 10 < 25 < series["water_level"][-1][1]
    assert series["soil_moisture"][0][1] < 50 < 80 < series["soil_moisture"][-1][1]
    assert max(value for offset, value in series["tilt"] if offset < 260) < 2
    assert series["tilt"][-1][1] > 2

    await runtime.start()
    await replay(runtime, scenario, clock)
    reasons = {event["payload"]["reason"] for event in events(runtime, "trigger")}
    assert {"water_rate_of_rise", "soil_moisture", "tilt"} <= reasons
    await runtime.close()
