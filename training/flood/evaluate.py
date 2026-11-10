"""Compare the VV threshold baseline and the U-Net on the same events and the same pixels.

    python -m training.flood.evaluate --cache <cache> --run <run dir> --split val
    python -m training.flood.evaluate --cache <cache> --run <run dir> --split test

Both thresholds come from validation data. A test report is written once: a second attempt stops
before reading any test tile, so test scores cannot steer later changes.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

import numpy as np

from training.flood.data import DB_MAX, DB_MIN, IGNORE, normalise
from training.flood.metrics import ScoreHistogram, report

Scorer = Callable[[np.ndarray], np.ndarray]


def vv_score(vv_db: np.ndarray) -> np.ndarray:
    """Map VV backscatter to [0, 1]. Open water returns little signal, so lower dB scores higher."""
    return np.clip((DB_MAX - vv_db) / (DB_MAX - DB_MIN), 0.0, 1.0)


def score_to_db(score: float) -> float:
    return DB_MAX - score * (DB_MAX - DB_MIN)


def baseline_scorer(x: np.ndarray) -> np.ndarray:
    return vv_score(x[0].astype(np.float32))


def score_tiles(tiles: list, cache: Path, scorer: Scorer) -> dict[str, ScoreHistogram]:
    """One histogram per event, counting only pixels with a valid label."""
    by_event: dict[str, ScoreHistogram] = defaultdict(ScoreHistogram)
    for event, name in tiles:
        x = np.load(cache / f"{name}.x.npy")
        y = np.load(cache / f"{name}.y.npy")
        keep = y != IGNORE
        by_event[event].add(scorer(x)[keep], y[keep])
    return dict(by_event)


def pooled_best_threshold(by_event: dict[str, ScoreHistogram]) -> float:
    total = ScoreHistogram()
    for hist in by_event.values():
        total.merge(hist)
    return total.best_threshold()


def unet_scorer(checkpoint: Path, stats: dict) -> tuple[Scorer, dict]:
    import torch

    from training.flood.model import FloodUNet, predict_tile

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    state = torch.load(checkpoint, map_location=device, weights_only=True)
    model = FloodUNet(pretrained=False, encoder=state.get("encoder", "resnet34")).to(device)
    model.load_state_dict(state["model"])
    model.eval()

    def score(x: np.ndarray) -> np.ndarray:
        return predict_tile(model, normalise(x, stats), device, window=state["window"])

    return score, {"threshold": state["threshold"], "epoch": state["epoch"]}


def usable(manifest: dict, split: str) -> list:
    bad = {f.split(":")[0] for f in manifest["failed"]}
    return [t for t in manifest["splits"][split] if t[1] not in bad]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--split", choices=["val", "test"], required=True)
    p.add_argument("--baseline-only", action="store_true", help="skip the U-Net; validation only")
    args = p.parse_args()

    out = args.run / f"report_{args.split}.json"
    if args.split == "test":
        if args.baseline_only:
            p.error("the test events are scored once, with both models together")
        if out.exists():
            p.error(f"{out} already exists; the test events have been scored")

    manifest = json.loads((args.cache / "manifest.json").read_text(encoding="utf-8"))
    val = usable(manifest, "val")
    threshold = pooled_best_threshold(score_tiles(val, args.cache, baseline_scorer))
    tiles = usable(manifest, args.split)

    baseline = report(score_tiles(tiles, args.cache, baseline_scorer), threshold)
    summary = {
        "split": args.split,
        "tiles": len(tiles),
        "baseline": {**baseline, "threshold_db": score_to_db(threshold)},
    }
    if not args.baseline_only:
        scorer, meta = unet_scorer(args.run / "best.pt", manifest["stats"])
        summary["unet"] = {
            **report(score_tiles(tiles, args.cache, scorer), meta["threshold"]),
            "best_epoch": meta["epoch"],
        }

    args.run.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    for name in ("baseline", "unet"):
        if name in summary:
            s = summary[name]
            print(
                f"{name}: threshold {s['all_pixels']['threshold']:.3f}"
                f" F1 {s['all_pixels']['f1']:.3f} IoU {s['all_pixels']['iou']:.3f}"
                f" mean-event F1 {s['mean_event_f1']:.3f} IoU {s['mean_event_iou']:.3f}",
                flush=True,
            )


if __name__ == "__main__":
    main()
