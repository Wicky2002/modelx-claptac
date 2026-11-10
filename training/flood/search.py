"""Search the flood model's training settings with a small genetic algorithm.

    python -m training.flood.search --cache <cache> --out <search dir> --max-hours 8

Every candidate trains on the training events minus a fixed group held out of them, and is scored on
that group. The validation and test events play no part, so they can still judge the winner fairly.
Safe to stop: rerunning with the same --out continues, and finished candidates are not trained again.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

# name: (low, high, log scale). Each gene is a number from 0 to 1 that decode() maps onto this range.
SPACE = {
    "lr": (2e-4, 3e-3, True),
    "encoder_ratio": (0.03, 1.0, True),
    "weight_decay": (1e-5, 0.1, True),
    "pos_weight": (0.5, 4.0, True),
    "dice_weight": (0.25, 2.0, True),
    "flood_crops": (0.2, 0.8, False),
}
CURRENT = {
    "lr": 1e-3,
    "encoder_ratio": 0.1,
    "weight_decay": 0.01,
    "pos_weight": 1.0,
    "dice_weight": 1.0,
    "flood_crops": 0.5,
}


def decode(genome: list[float]) -> dict[str, float]:
    settings = {}
    for gene, (name, (low, high, log)) in zip(genome, SPACE.items()):
        if log:
            settings[name] = math.exp(math.log(low) + gene * (math.log(high) - math.log(low)))
        else:
            settings[name] = low + gene * (high - low)
    return settings


def encode(settings: dict[str, float]) -> list[float]:
    genome = []
    for name, (low, high, log) in SPACE.items():
        value = settings[name]
        if log:
            genome.append((math.log(value) - math.log(low)) / (math.log(high) - math.log(low)))
        else:
            genome.append((value - low) / (high - low))
    return genome


def first_generation(size: int, rng: random.Random) -> list[list[float]]:
    """Today's settings, so the search has to beat them, plus random ones."""
    return [encode(CURRENT)] + [[rng.random() for _ in SPACE] for _ in range(size - 1)]


def tournament(scored: list[tuple[list[float], float]], rng: random.Random) -> list[float]:
    return max(rng.sample(scored, min(3, len(scored))), key=lambda s: s[1])[0]


def child(a: list[float], b: list[float], rng: random.Random, sigma: float = 0.12) -> list[float]:
    """Each gene is a random blend of the parents, nudged by Gaussian noise and kept within 0 to 1."""
    out = []
    for x, y in zip(a, b):
        mix = rng.random()
        out.append(min(1.0, max(0.0, mix * x + (1 - mix) * y + rng.gauss(0, sigma))))
    return out


def next_generation(
    scored: list[tuple[list[float], float]], count: int, rng: random.Random
) -> list[list[float]]:
    """New candidates only. The best from earlier generations stay in `scored` and are never retrained."""
    return [child(tournament(scored, rng), tournament(scored, rng), rng) for _ in range(count)]


def fitness(rows: list[dict], last: int = 3) -> float:
    """Mean event F1 over the last few checks. One check is noisy, and the best of many flatters."""
    checks = [r["val"]["mean_event_f1"] for r in rows if "val" in r]
    if not checks:
        raise ValueError("no scored epochs")
    return sum(checks[-last:]) / len(checks[-last:])


def evaluate(index: int, genome: list[float], args: argparse.Namespace) -> float:
    run = args.out / f"candidate-{index:03d}"
    settings = decode(genome)
    command = [
        sys.executable, "-m", "training.flood.train",
        "--cache", str(args.cache), "--run", str(run),
        "--epochs", str(args.epochs), "--val-every", "2", "--hold-out", str(args.hold_out),
        "--seed", str(args.seed),
    ]  # fmt: skip
    for name, value in settings.items():
        command += [f"--{name.replace('_', '-')}", f"{value:.6g}"]
    run.mkdir(parents=True, exist_ok=True)
    with open(run / "console.log", "a", encoding="utf-8") as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    lines = (run / "metrics.jsonl").read_text(encoding="utf-8").splitlines()
    score = fitness([json.loads(line) for line in lines])
    for name in ("best.pt", "last.pt"):  # a candidate's weights are never used again
        (run / name).unlink(missing_ok=True)
    return score


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--population", type=int, default=6)
    p.add_argument("--generations", type=int, default=4, help="including the first")
    p.add_argument("--children", type=int, default=4, help="new candidates per later generation")
    p.add_argument("--epochs", type=int, default=12)
    p.add_argument("--hold-out", type=int, default=10, help="events held out of training")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--max-hours", type=float, default=0, help="stop between candidates; 0 = no limit")
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    history_path = args.out / "history.jsonl"
    done = []
    if history_path.exists():
        done = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines()]

    began = time.time()
    planned: list[list[float]] = []
    for generation in range(args.generations):
        # The random stream is rebuilt from the seed, so a resumed search plans the same candidates.
        rng = random.Random(f"{args.seed}-{generation}")
        if generation == 0:
            batch = first_generation(args.population, rng)
        else:
            scored = [(d["genome"], d["fitness"]) for d in done[: len(planned)]]
            batch = next_generation(scored, args.children, rng)
        for genome in batch:
            index = len(planned)
            planned.append(genome)
            if index < len(done):
                continue
            if args.max_hours and (time.time() - began) / 3600 >= args.max_hours:
                print("time budget reached; rerun to continue", flush=True)
                _write_best(done, args.out)
                return
            if (args.out / f"candidate-{index:03d}").exists():
                shutil.rmtree(args.out / f"candidate-{index:03d}")  # stopped part-way last time
            t0 = time.time()
            score = evaluate(index, genome, args)
            row = {
                "index": index,
                "generation": generation,
                "genome": genome,
                "settings": decode(genome),
                "fitness": score,
                "minutes": round((time.time() - t0) / 60, 1),
            }
            done.append(row)
            with open(history_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")
            print(row, flush=True)
            _write_best(done, args.out)
    print("search finished", flush=True)


def _write_best(done: list[dict], out: Path) -> None:
    if done:
        best = max(done, key=lambda d: d["fitness"])
        (out / "best.json").write_text(json.dumps(best, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
