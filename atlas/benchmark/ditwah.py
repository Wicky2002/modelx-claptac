"""Strict Ditwah replay: when would the rules have warned, using only what was known at the time?

    python -m atlas.benchmark.ditwah

The committed scenario is compressed 240x for demos, which also compresses the Sentinel's rate-of-rise
window. Evaluation therefore replays at real speed:

    strict      Gauge readings only, each at its own time. ERA5 is excluded: reanalysis is published
                days later, so it could not have been used during the flood (§9).
    assisted    Gauge plus ERA5 rain and soil at their nominal time. Reported separately, because it
                is not something an operator could have had.
    demo_240x   The compressed demo, for contrast. Its times are not a warning-time result.

Times are converted back to real time from the gauge's own measurement timestamps.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from atlas.core.config import SentinelConfig, Settings
from atlas.ingest.simulator import ReplayClock, replay
from atlas.runtime import Runtime

SCENARIO = Path(__file__).resolve().parents[2] / "data/scenarios/ratnapura_ditwah_2025.json"
METRES_PER_CM = 0.20  # the scale the scenario was built with (data/reference/sensor_map.yaml)
ALERT_M, MINOR_M, MAJOR_M = 5.2, 7.5, 9.5  # department levels for the station, checked in docs
MODES = ("strict", "assisted", "demo_240x")


def load(path: Path = SCENARIO) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def is_reanalysis(entry: dict) -> bool:
    return entry["payload"]["node_id"].startswith("open-meteo")


def _measured(entry: dict) -> int:
    return int(entry["payload"]["measurement_id"].rsplit("-", 1)[1])


def origin_of(scenario: dict) -> datetime:
    """The first gauge reading's true time. The file's ``real_start`` label is local, not UTC."""
    first = next(e for e in scenario["events"] if not is_reanalysis(e))
    return datetime.fromtimestamp(_measured(first), timezone.utc)


def entries_for(scenario: dict, mode: str) -> list[dict]:
    """The inputs a mode may see, each at the moment it arrives."""
    if mode == "demo_240x":
        return scenario["events"]
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode}")
    speedup, start = scenario["speedup"], _measured(scenario["events"][0])
    out = []
    for entry in scenario["events"]:
        if is_reanalysis(entry):
            if mode == "strict":
                continue
            at = int(entry["at_seconds"] * speedup)
        else:
            at = _measured(entry) - start
        out.append({**entry, "at_seconds": at})
    return sorted(out, key=lambda e: e["at_seconds"])


def crossing(scenario: dict, level_m: float) -> datetime | None:
    for entry in scenario["events"]:
        payload = entry["payload"]
        if payload["type"] == "water_level" and payload["value"] * METRES_PER_CM >= level_m:
            return datetime.fromtimestamp(_measured(entry), timezone.utc)
    return None


def _hours(earlier: datetime | None, later: datetime | None) -> float | None:
    return round((later - earlier).total_seconds() / 3600, 2) if earlier and later else None


async def run_mode(scenario: dict, mode: str) -> dict:
    origin = origin_of(scenario)
    clock = ReplayClock(origin)
    runtime = Runtime(Settings(database_path=":memory:", sentinel=SentinelConfig()), clock=clock)
    entries = entries_for(scenario, mode)
    try:
        await runtime.start()
        await replay(runtime, {"name": scenario["name"], "events": entries}, clock)
        events = [r["payload"] for r in runtime.ledger.records("event")]
    finally:
        await runtime.close()
    scale = scenario["speedup"] if mode == "demo_240x" else 1
    triggers = sorted(
        (
            (
                origin + (datetime.fromisoformat(e["created_at"]) - origin) * scale,
                e["payload"]["reason"],
                e["payload"]["hazard"],
            )
            for e in events
            if e["type"] == "trigger"
        ),
        key=lambda t: t[0],
    )
    flood = [t for t in triggers if t[2] == "flood"]
    first, major = (flood[0][0] if flood else None), crossing(scenario, MAJOR_M)
    return {
        "mode": mode,
        "inputs": len(entries),
        "first_flood_trigger": first.isoformat() if first else None,
        "first_trigger_reason": flood[0][1] if flood else None,
        "major_flood_crossing": major.isoformat() if major else None,
        "lead_hours_before_major": _hours(first, major),
        "flood_triggers": len(flood),
    }


def anchors(scenario: dict) -> dict:
    levels = [
        (_measured(e), e["payload"]["value"] * METRES_PER_CM)
        for e in scenario["events"]
        if e["payload"]["type"] == "water_level"
    ]
    moment, peak = max(levels, key=lambda item: item[1])
    gaps = [b[0] - a[0] for a, b in zip(levels, levels[1:])]
    return {
        "peak_m": round(peak, 2),
        "peak_at_utc": datetime.fromtimestamp(moment, timezone.utc).isoformat(),
        "gauge_readings": len(levels),
        "longest_gap_hours": round(max(gaps) / 3600, 2),
        "first_reading_utc": origin_of(scenario).isoformat(),
        "alert_crossing_utc": crossing(scenario, ALERT_M).isoformat(),
        "minor_crossing_utc": crossing(scenario, MINOR_M).isoformat(),
        "major_crossing_utc": crossing(scenario, MAJOR_M).isoformat(),
        "last_reading_utc": datetime.fromtimestamp(levels[-1][0], timezone.utc).isoformat(),
    }


async def evaluate(path: Path = SCENARIO) -> dict:
    scenario = load(path)
    return {
        "anchors": anchors(scenario),
        "results": [await run_mode(scenario, mode) for mode in MODES],
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(evaluate()), indent=2))
