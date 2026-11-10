"""Combine trained flood models: average several, average over flips and rotations, smooth, then threshold.

    python -m training.flood.combine --cache <cache> --runs <run> <run> ... --out <dir> --split val
    python -m training.flood.combine --cache <cache> --runs <run> <run> ... --out <dir> --split test

On validation it tries every subset of the runs, with and without the eight flips and rotations, and a
few smoothing widths, and keeps the best by mean event F1. The test events are then scored once with that
choice only, beside the VV baseline. A second test attempt stops before reading any test tile.
"""

from __future__ import annotations

import argparse
import itertools
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from training.flood.data import IGNORE, normalise
from training.flood.evaluate import baseline_scorer, pooled_best_threshold, score_to_db, usable
from training.flood.metrics import ScoreHistogram, report

SMOOTHING = (1, 3, 5, 7)


def dihedral(x: np.ndarray, k: int) -> np.ndarray:
    """One of the eight flips and rotations of the last two axes (k from 0 to 7)."""
    out = np.rot90(x, k % 4, axes=(-2, -1))
    return out[..., ::-1] if k >= 4 else out


def undo_dihedral(x: np.ndarray, k: int) -> np.ndarray:
    if k >= 4:
        x = x[..., ::-1]
    return np.rot90(x, -(k % 4), axes=(-2, -1))


def smooth(p: np.ndarray, width: int) -> np.ndarray:
    """Mean over a width x width square, so isolated specks fall below the threshold."""
    if width <= 1:
        return p
    pad = width // 2
    padded = np.pad(p.astype(np.float64), pad, mode="edge")
    total = np.pad(padded.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    h, w = p.shape
    s = (
        total[width : width + h, width : width + w]
        - total[:h, width : width + w]
        - total[width : width + h, :w]
        + total[:h, :w]
    )
    return (s / (width * width)).astype(np.float32)


def options(members: list[str]) -> list[dict]:
    out = []
    for size in range(1, len(members) + 1):
        for subset in itertools.combinations(members, size):
            for tta in (False, True):
                for width in SMOOTHING:
                    out.append({"members": list(subset), "tta": tta, "smooth": width})
    return out


def load(run: Path, device):
    import torch

    from training.flood.model import FloodUNet

    state = torch.load(run / "best.pt", map_location=device, weights_only=True)
    model = FloodUNet(pretrained=False, encoder=state.get("encoder", "resnet34")).to(device)
    model.load_state_dict(state["model"])
    model.eval()
    return model, state["window"]


def probability(model, window, x, stats, device, tta: bool) -> np.ndarray:
    """Flood probability for one raw tile, optionally averaged over the eight flips and rotations."""
    from training.flood.model import predict_tile

    x = normalise(x, stats)
    if not tta:
        return predict_tile(model, x, device, window=window)
    total = np.zeros(x.shape[1:], dtype=np.float32)
    for k in range(8):
        turned = np.ascontiguousarray(dihedral(x, k))
        total += np.ascontiguousarray(undo_dihedral(predict_tile(model, turned, device, window=window), k))
    return total / 8


def _cached(run: Path, tiles, cache: Path, stats, out: Path, tta: bool, device) -> Path:
    """Validation probabilities for one run, saved so that every combination reuses them."""
    folder = out / "probabilities" / f"{run.name}{'-tta' if tta else ''}"
    if (folder / "done").exists():
        return folder
    folder.mkdir(parents=True, exist_ok=True)
    model, window = load(run, device)
    for _, name in tiles:
        x = np.load(cache / f"{name}.x.npy")
        p = probability(model, window, x, stats, device, tta)
        np.save(folder / f"{name}.npy", p.astype(np.float16))
    (folder / "done").write_text("", encoding="utf-8")
    return folder


def _histograms(tiles, cache: Path, score) -> dict[str, ScoreHistogram]:
    by_event: dict[str, ScoreHistogram] = defaultdict(ScoreHistogram)
    for event, name in tiles:
        y = np.load(cache / f"{name}.y.npy")
        keep = y != IGNORE
        by_event[event].add(score(name)[keep], y[keep])
    return dict(by_event)


def _baseline(cache: Path):
    return lambda tile: baseline_scorer(np.load(cache / f"{tile}.x.npy"))


def main() -> None:
    import torch

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--runs", type=Path, nargs="+", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--split", choices=["val", "test"], required=True)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    manifest = json.loads((args.cache / "manifest.json").read_text(encoding="utf-8"))
    stats = manifest["stats"]
    runs = {r.name: r for r in args.runs}

    if args.split == "val":
        tiles = usable(manifest, "val")
        folders = {}
        for name, run in runs.items():
            for tta in (False, True):
                folders[(name, tta)] = _cached(run, tiles, args.cache, stats, args.out, tta, device)
                print("probabilities ready", name, "tta" if tta else "", flush=True)
        table = []
        for option in options(list(runs)):

            def score(tile, option=option):
                parts = [
                    np.load(folders[(m, option["tta"])] / f"{tile}.npy").astype(np.float32)
                    for m in option["members"]
                ]
                return smooth(np.mean(parts, axis=0), option["smooth"])

            by_event = _histograms(tiles, args.cache, score)
            threshold = pooled_best_threshold(by_event)
            scores = report(by_event, threshold)
            row = {
                **option,
                "threshold": threshold,
                "mean_event_f1": scores["mean_event_f1"],
                "mean_event_iou": scores["mean_event_iou"],
                "all_pixels": scores["all_pixels"],
            }
            table.append(row)
            print({k: row[k] for k in ("members", "tta", "smooth", "mean_event_f1")}, flush=True)
        table.sort(key=lambda r: -r["mean_event_f1"])
        (args.out / "val_table.json").write_text(json.dumps(table, indent=2), encoding="utf-8")
        (args.out / "choice.json").write_text(json.dumps(table[0], indent=2), encoding="utf-8")
        print("chosen", table[0], flush=True)
        return

    out = args.out / "report_test.json"
    if out.exists():
        p.error(f"{out} already exists; the test events have been scored")
    choice = json.loads((args.out / "choice.json").read_text(encoding="utf-8"))
    val, tiles = usable(manifest, "val"), usable(manifest, "test")
    models = [load(runs[m], device) for m in choice["members"]]

    def combined(tile):
        x = np.load(args.cache / f"{tile}.x.npy")
        parts = [probability(m, w, x, stats, device, choice["tta"]) for m, w in models]
        return smooth(np.mean(parts, axis=0), choice["smooth"])

    base_threshold = pooled_best_threshold(_histograms(val, args.cache, _baseline(args.cache)))
    summary = {
        "split": "test",
        "tiles": len(tiles),
        "choice": {k: choice[k] for k in ("members", "tta", "smooth", "threshold")},
        "baseline": {
            **report(_histograms(tiles, args.cache, _baseline(args.cache)), base_threshold),
            "threshold_db": score_to_db(base_threshold),
        },
        "combined": report(_histograms(tiles, args.cache, combined), choice["threshold"]),
    }
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    for name in ("baseline", "combined"):
        s = summary[name]
        print(
            f"{name}: F1 {s['all_pixels']['f1']:.3f} IoU {s['all_pixels']['iou']:.3f}"
            f" mean-event F1 {s['mean_event_f1']:.3f} IoU {s['mean_event_iou']:.3f}",
            flush=True,
        )


if __name__ == "__main__":
    main()
