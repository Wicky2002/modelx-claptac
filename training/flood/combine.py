"""Combine trained flood models into one calibrated, terrain-aware flood map with an uncertainty layer.

    python -m training.flood.combine --cache <cache> --runs <run> <run> ... --out <dir> --split val
    python -m training.flood.combine --cache <cache> --runs <run> <run> ... --out <dir> --split test

Validation, in two stages so the choices stay few:
  1. which runs to average, with or without the eight flips and rotations;
  2. for that pick, how much to smooth and which slopes to rule out. Radar shadow on steep slopes is
     dark like water, and flood water cannot rest on a steep slope.
Then one temperature is fitted so that the probabilities mean what they say, and the spread between the
runs gives a per-pixel uncertainty. The test events are scored once with these choices, beside the VV
baseline. A second test attempt stops before reading any test tile.
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
SLOPES = (None, 10.0, 15.0, 20.0, 30.0)
PIXEL_M = 10.0  # MMFlood tiles and the Sentinel-1 scenes are about 10 m
TEMPERATURES = tuple(np.round(np.exp(np.linspace(np.log(0.25), np.log(4.0), 41)), 4))


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


def slope_degrees(relative: np.ndarray, pixel_m: float = PIXEL_M) -> np.ndarray:
    """Slope from the relative-elevation channel, which is height in hundreds of metres."""
    dy, dx = np.gradient(relative.astype(np.float32) * 100.0, pixel_m)
    return np.degrees(np.arctan(np.hypot(dx, dy))).astype(np.float32)


def finish(parts: list[np.ndarray], width: int, slope: np.ndarray | None, cutoff) -> np.ndarray:
    """Average the runs, smooth, and rule out slopes steeper than the cutoff."""
    p = smooth(np.mean(parts, axis=0), width)
    if cutoff is not None and slope is not None:
        p = np.where(slope > cutoff, 0.0, p).astype(np.float32)
    return p


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p.astype(np.float64), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def calibrate(p: np.ndarray, temperature: float) -> np.ndarray:
    return (1 / (1 + np.exp(-logit(p) / temperature))).astype(np.float32)


def fit_temperature(p: np.ndarray, y: np.ndarray) -> float:
    """The temperature with the lowest log loss. Fitted on validation pixels only."""
    z = logit(p)
    best, best_loss = 1.0, np.inf
    for t in TEMPERATURES:
        q = np.clip(1 / (1 + np.exp(-z / t)), 1e-6, 1 - 1e-6)
        loss = -np.mean(y * np.log(q) + (1 - y) * np.log(1 - q))
        if loss < best_loss:
            best, best_loss = float(t), loss
    return best


def expected_calibration_error(p: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    """How far stated probabilities sit from observed flood rates, weighted by pixel count."""
    idx = np.minimum((p * bins).astype(int), bins - 1)
    error = 0.0
    for b in range(bins):
        sel = idx == b
        if sel.any():
            error += sel.mean() * abs(p[sel].mean() - y[sel].mean())
    return float(error)


def first_stage(members: list[str]) -> list[dict]:
    out = []
    for size in range(1, len(members) + 1):
        for subset in itertools.combinations(members, size):
            for tta in (False, True):
                out.append({"members": list(subset), "tta": tta, "smooth": 1, "slope": None})
    return out


def second_stage(pick: dict) -> list[dict]:
    return [{**pick, "smooth": w, "slope": s} for w in SMOOTHING for s in SLOPES]


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


def _pixels(tiles, cache: Path, score, step: int = 37):
    """A thinned sample of valid pixels: probabilities and labels, for calibration."""
    ps, ys = [], []
    for _, name in tiles:
        y = np.load(cache / f"{name}.y.npy").ravel()
        p = score(name).ravel()
        keep = np.flatnonzero(y != IGNORE)[::step]
        ps.append(p[keep])
        ys.append(y[keep].astype(np.float64))
    return np.concatenate(ps), np.concatenate(ys)


def _baseline(cache: Path):
    return lambda tile: baseline_scorer(np.load(cache / f"{tile}.x.npy"))


def _row(option: dict, by_event) -> dict:
    threshold = pooled_best_threshold(by_event)
    scores = report(by_event, threshold)
    return {
        **option,
        "threshold": threshold,
        "mean_event_f1": scores["mean_event_f1"],
        "mean_event_iou": scores["mean_event_iou"],
        "all_pixels": scores["all_pixels"],
    }


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
        slopes = {n: slope_degrees(np.load(args.cache / f"{n}.x.npy")[2]) for _, n in tiles}

        def scorer(option):
            def score(tile):
                parts = [
                    np.load(folders[(m, option["tta"])] / f"{tile}.npy").astype(np.float32)
                    for m in option["members"]
                ]
                return finish(parts, option["smooth"], slopes[tile], option["slope"])

            return score

        table = []
        for option in first_stage(list(runs)):
            table.append(_row(option, _histograms(tiles, args.cache, scorer(option))))
            print({k: table[-1][k] for k in ("members", "tta", "mean_event_f1")}, flush=True)
        pick = max(table, key=lambda r: r["mean_event_f1"])
        pick = {k: pick[k] for k in ("members", "tta", "smooth", "slope")}
        for option in second_stage(pick):
            if option == pick:
                continue
            table.append(_row(option, _histograms(tiles, args.cache, scorer(option))))
            print({k: table[-1][k] for k in ("smooth", "slope", "mean_event_f1")}, flush=True)
        table.sort(key=lambda r: -r["mean_event_f1"])
        choice = dict(table[0])
        sample_p, sample_y = _pixels(tiles, args.cache, scorer(choice))
        choice["temperature"] = fit_temperature(sample_p, sample_y)
        choice["val_ece_before"] = expected_calibration_error(sample_p, sample_y)
        choice["val_ece_after"] = expected_calibration_error(
            calibrate(sample_p, choice["temperature"]), sample_y
        )
        choice["calibrated_threshold"] = float(
            calibrate(np.array([choice["threshold"]]), choice["temperature"])[0]
        )
        (args.out / "val_table.json").write_text(json.dumps(table, indent=2), encoding="utf-8")
        (args.out / "choice.json").write_text(json.dumps(choice, indent=2), encoding="utf-8")
        print("chosen", {k: v for k, v in choice.items() if k != "all_pixels"}, flush=True)
        return

    out = args.out / "report_test.json"
    if out.exists():
        p.error(f"{out} already exists; the test events have been scored")
    choice = json.loads((args.out / "choice.json").read_text(encoding="utf-8"))
    val, tiles = usable(manifest, "val"), usable(manifest, "test")
    models = [load(runs[m], device) for m in choice["members"]]
    memo: dict[str, np.ndarray] = {}

    def combined(tile):
        if tile not in memo:
            memo.clear()  # one tile at a time: scored for the histogram, then for calibration
            x = np.load(args.cache / f"{tile}.x.npy")
            parts = [probability(m, w, x, stats, device, choice["tta"]) for m, w in models]
            memo[tile] = finish(parts, choice["smooth"], slope_degrees(x[2]), choice["slope"])
        return memo[tile]

    by_event: dict[str, ScoreHistogram] = defaultdict(ScoreHistogram)
    ps, ys = [], []
    for event, name in tiles:
        y = np.load(args.cache / f"{name}.y.npy")
        keep = y != IGNORE
        score = combined(name)
        by_event[event].add(score[keep], y[keep])
        flat = np.flatnonzero(keep.ravel())[::37]
        ps.append(score.ravel()[flat])
        ys.append(y.ravel()[flat].astype(np.float64))
    sample_p, sample_y = np.concatenate(ps), np.concatenate(ys)

    base_threshold = pooled_best_threshold(_histograms(val, args.cache, _baseline(args.cache)))
    keys = ("members", "tta", "smooth", "slope", "threshold", "temperature")
    summary = {
        "split": "test",
        "tiles": len(tiles),
        "choice": {k: choice[k] for k in keys},
        "baseline": {
            **report(_histograms(tiles, args.cache, _baseline(args.cache)), base_threshold),
            "threshold_db": score_to_db(base_threshold),
        },
        "combined": report(dict(by_event), choice["threshold"]),
        "calibration": {
            "ece_before": expected_calibration_error(sample_p, sample_y),
            "ece_after": expected_calibration_error(
                calibrate(sample_p, choice["temperature"]), sample_y
            ),
        },
    }
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    for name in ("baseline", "combined"):
        s = summary[name]
        print(
            f"{name}: F1 {s['all_pixels']['f1']:.3f} IoU {s['all_pixels']['iou']:.3f}"
            f" mean-event F1 {s['mean_event_f1']:.3f} IoU {s['mean_event_iou']:.3f}",
            flush=True,
        )
    print("calibration", summary["calibration"], flush=True)


if __name__ == "__main__":
    main()
