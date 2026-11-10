"""Convert real Pi-node JSONL recordings into an ATLAS bench-test replay.

Run: python -m atlas.datasets.bench_recording node-1.jsonl node-2.jsonl \
    --name ratnapura-bench --output data/scenarios/ratnapura_bench.json
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from atlas.datasets.to_scenario import readings_to_scenario
from atlas.ingest.sensors import SensorReading

REQUIRED_TYPES = {"water_level", "soil_moisture", "tilt"}


def load_recordings(paths: list[Path]) -> list[SensorReading]:
    """Validate every recorded measurement and merge recordings from multiple nodes."""
    readings = []
    seen = {}
    for path in paths:
        with path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                try:
                    reading = SensorReading.model_validate_json(line)
                except ValueError as exc:
                    raise ValueError(
                        f"{path}:{line_number}: invalid sensor reading: {exc}"
                    ) from exc
                if not reading.measurement_id:
                    raise ValueError(f"{path}:{line_number}: missing measurement_id")
                identity = (reading.node_id, reading.sensor_id, reading.measurement_id)
                previous = seen.get(identity)
                if previous is not None:
                    if previous != reading:
                        raise ValueError(f"{path}:{line_number}: conflicting duplicate {identity}")
                    continue
                seen[identity] = reading
                readings.append(reading)
    if not readings:
        raise ValueError("recording has no readings")
    return sorted(readings, key=lambda reading: reading.timestamp)


def build_bench_scenario(readings: list[SensorReading], name: str) -> dict:
    """Keep the raw values and source IDs; never label a bench run as a disaster."""
    kinds = {reading.type.value for reading in readings}
    missing = REQUIRED_TYPES - kinds
    if missing:
        raise ValueError(f"bench recording is missing: {', '.join(sorted(missing))}")
    areas = {reading.location.area_id for reading in readings if reading.location}
    if len(areas) != 1 or None in areas or any(reading.location is None for reading in readings):
        raise ValueError("all readings must carry the same nonempty area_id")

    scenario = readings_to_scenario(readings, name)
    ranges = defaultdict(list)
    for reading in readings:
        ranges[f"{reading.type.value} ({reading.unit})"].append(reading.value)
    scenario.update(
        title=f"{name}: recorded hardware bench test",
        hazard="landslide",
        area_id=next(iter(areas)),
        real=False,
        recording_kind="bench_test",
        recorded_from=readings[0].timestamp.isoformat(),
        recorded_until=readings[-1].timestamp.isoformat(),
        replay_minutes=round(scenario["events"][-1]["at_seconds"] / 60, 2),
        observed_ranges={
            key: {"min": min(values), "max": max(values)} for key, values in sorted(ranges.items())
        },
        assumptions=[
            "Real sensor readings from a controlled bench test; not a real landslide or a field warning.",
            "Compare recorded water levels with data/reference/sensor_map.yaml before using the replay.",
        ],
    )
    return scenario


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "recordings", nargs="+", type=Path, help="JSONL from Pi node recording_path"
    )
    parser.add_argument("--name", required=True, help="Scenario name")
    parser.add_argument("--output", required=True, type=Path, help="Scenario JSON path")
    args = parser.parse_args()
    scenario = build_bench_scenario(load_recordings(args.recordings), args.name)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(scenario, output, indent=2)
        output.write("\n")
    print(f"wrote {args.output} ({len(scenario['events'])} readings)")
    print(json.dumps(scenario["observed_ranges"], indent=2))


if __name__ == "__main__":
    main()
