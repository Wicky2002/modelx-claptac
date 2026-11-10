"""Generate a repeatable synthetic tabletop sensor session for the H3 replay workflow.

Run: python -m atlas.datasets.synthetic_bench --output data/scenarios/ratnapura_synthetic_bench.json
These values are simulated; use ``bench_recording`` for measurements from real hardware.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from atlas.datasets.to_scenario import readings_to_scenario
from atlas.ingest.sensors import SensorReading

NAME = "ratnapura-synthetic-bench"
AREA_ID = "ratnapura-demo-river"
SEED = 1709
START = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)
LOCATION = {"lat": 6.6828, "lon": 80.3992, "area_id": AREA_ID}


def ramp(seconds: int, beginning: int, end: int) -> float:
    """Smooth step gives a hand-poured or hand-tilted change without instant jumps."""
    progress = min(1.0, max(0.0, (seconds - beginning) / (end - beginning)))
    return progress * progress * (3 - 2 * progress)


def build_scenario() -> dict:
    rng = random.Random(SEED)
    readings = []
    ranges = defaultdict(list)
    for seconds in range(0, 601, 10):
        water = 6.0 + 24.0 * ramp(seconds, 60, 510) + rng.uniform(-0.18, 0.18)
        soil = 46.0 + 44.0 * ramp(seconds, 70, 540) + rng.uniform(-0.45, 0.45)
        tilt = 0.12 + 2.62 * ramp(seconds, 260, 510) + rng.uniform(-0.04, 0.04)
        # One small handling vibration is below the A1 threshold; sustained tilt crosses it later.
        if seconds == 150:
            tilt += 0.85
        values = (
            ("bench-river-01", "water-01", "water_level", round(water, 2), "cm"),
            ("bench-slope-02", "soil-01", "soil_moisture", round(soil, 2), "%"),
            ("bench-slope-02", "tilt-01", "tilt", round(tilt, 2), "deg"),
        )
        for node_id, sensor_id, kind, value, unit in values:
            readings.append(
                SensorReading(
                    node_id=node_id,
                    sensor_id=sensor_id,
                    measurement_id=f"synthetic-{sensor_id}-{seconds:03d}",
                    type=kind,
                    value=value,
                    unit=unit,
                    timestamp=START + timedelta(seconds=seconds),
                    location=LOCATION,
                )
            )
            ranges[f"{kind} ({unit})"].append(value)

    scenario = readings_to_scenario(readings, NAME)
    scenario.update(
        title="Ratnapura tabletop sensors (synthetic exercise)",
        hazard="landslide",
        area_id=AREA_ID,
        real=False,
        recording_kind="synthetic_bench",
        source="deterministic simulation; no hardware measurements",
        seed=SEED,
        story=(
            "Two simulated nodes sample every 10 seconds. A container fills, soil is wetted, "
            "and a slope board gradually tilts after one brief vibration."
        ),
        replay_minutes=10.0,
        observed_ranges={
            key: {"min": min(values), "max": max(values)} for key, values in sorted(ranges.items())
        },
        assumptions=[
            "All measurements are synthetic and are not evidence of a real disaster or hardware performance.",
            "Water uses the 0–40 cm tabletop scale in data/reference/sensor_map.yaml, not river depth.",
            "Tilt is degrees from the installed angle; the 2-degree A1 threshold is a demo value.",
            "The coordinates and area ID are the existing Ratnapura demo mapping, not a physical bench site.",
        ],
    )
    return scenario


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    scenario = build_scenario()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(scenario, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output} ({len(scenario['events'])} synthetic readings)")


if __name__ == "__main__":
    main()
