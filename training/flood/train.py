"""Train the radar flood U-Net. Safe to stop: rerunning with the same --run continues from the last epoch.

    python -m training.flood.train --cache <cache> --run <run dir> --epochs 40 --max-hours 8

Only training and validation events are used here. Test events are scored separately, once.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from training.flood.data import IGNORE, CropDataset, normalise
from training.flood.evaluate import pooled_best_threshold, score_tiles
from training.flood.metrics import report
from training.flood.model import FloodUNet, predict_tile


def hold_out(tiles: list, count: int) -> tuple[list, list]:
    """Whole events set aside from training, the same ones every time: (kept, held out)."""
    events = sorted({event for event, _ in tiles}, key=lambda e: hashlib.sha256(e.encode()).hexdigest())
    chosen = set(events[:count])
    return [t for t in tiles if t[0] not in chosen], [t for t in tiles if t[0] in chosen]


def loss_fn(logits, target, pos_weight: float, dice_weight: float = 1.0):
    """Class-weighted BCE plus Dice, ignoring no-data pixels."""
    valid = target != IGNORE
    y = (target == 1).float()
    bce = torch.nn.functional.binary_cross_entropy_with_logits(
        logits[valid], y[valid], pos_weight=torch.tensor(pos_weight, device=logits.device)
    )
    p = torch.sigmoid(logits) * valid
    t = y * valid
    dice = 1 - (2 * (p * t).sum() + 1) / (p.sum() + t.sum() + 1)
    return bce + dice_weight * dice


def validate(model, tiles, cache, stats, device, window: int) -> dict:
    """Scores at the best pooled threshold, plus the per-event mean used to choose the best epoch."""
    model.eval()
    by_event = score_tiles(
        tiles, cache, lambda x: predict_tile(model, normalise(x, stats), device, window=window)
    )
    scores = report(by_event, pooled_best_threshold(by_event))
    return {
        **scores["all_pixels"],
        "mean_event_f1": scores["mean_event_f1"],
        "mean_event_iou": scores["mean_event_iou"],
    }


def thin(tiles: list, limit: int) -> list:
    return tiles[:: max(1, len(tiles) // limit)][:limit] if limit else tiles


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--epochs", type=int, default=40)
    p.add_argument("--batch", type=int, default=8)
    p.add_argument("--crop", type=int, default=448, help="the smallest MMFlood tile side is 467")
    p.add_argument("--per-tile", type=int, default=2, help="crops per training tile per epoch")
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument(
        "--pos-weight", type=float, default=2.0, help="flood-centred crops already raise flood share"
    )
    p.add_argument("--encoder", choices=["resnet34", "resnet50"], default="resnet34")
    p.add_argument("--dice-weight", type=float, default=1.0)
    p.add_argument("--weight-decay", type=float, default=0.01)
    p.add_argument("--encoder-ratio", type=float, default=0.1, help="encoder lr as a share of --lr")
    p.add_argument("--flood-crops", type=float, default=0.5, help="share of crops centred on flood")
    p.add_argument(
        "--hold-out",
        type=int,
        default=0,
        help="score on N events held out of training instead of the validation events (settings search)",
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--val-every", type=int, default=2)
    p.add_argument("--max-hours", type=float, default=0, help="stop cleanly after this; 0 = no limit")
    p.add_argument("--limit-train", type=int, default=0, help="use only N training tiles (speed test)")
    p.add_argument("--limit-val", type=int, default=0, help="use only N validation tiles (speed test)")
    args = p.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    use_amp = device.type == "cuda"
    args.run.mkdir(parents=True, exist_ok=True)
    (args.run / "config.json").write_text(
        json.dumps({k: str(v) for k, v in vars(args).items()}, indent=2), encoding="utf-8"
    )

    manifest = json.loads((args.cache / "manifest.json").read_text(encoding="utf-8"))
    stats = manifest["stats"]
    bad = {f.split(":")[0] for f in manifest["failed"]}
    train_tiles = thin([t for t in manifest["splits"]["train"] if t[1] not in bad], args.limit_train)
    val_tiles = thin([t for t in manifest["splits"]["val"] if t[1] not in bad], args.limit_val)
    if args.hold_out:
        train_tiles, val_tiles = hold_out(train_tiles, args.hold_out)

    data = CropDataset(
        train_tiles, args.cache, stats, args.crop, args.per_tile, args.seed, args.flood_crops
    )
    loader = DataLoader(
        data,
        batch_size=args.batch,
        shuffle=True,
        num_workers=args.workers,
        drop_last=True,
        pin_memory=True,
    )
    model = FloodUNet(encoder=args.encoder).to(device)
    encoder = [q for n, q in model.named_parameters() if n.startswith(("stem", "encoder"))]
    decoder = [q for n, q in model.named_parameters() if not n.startswith(("stem", "encoder"))]
    opt = torch.optim.AdamW(
        [{"params": encoder, "lr": args.lr * args.encoder_ratio}, {"params": decoder}],
        lr=args.lr,
        weight_decay=args.weight_decay,
    )
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)
    scaler = torch.amp.GradScaler(device.type, enabled=use_amp)

    start, best = 0, -1.0
    last = args.run / "last.pt"
    if last.exists():
        state = torch.load(last, map_location=device, weights_only=True)
        model.load_state_dict(state["model"])
        opt.load_state_dict(state["opt"])
        sched.load_state_dict(state["sched"])
        scaler.load_state_dict(state["scaler"])
        start, best = state["epoch"] + 1, state["best"]
        print(f"continuing from epoch {start}", flush=True)

    began = time.time()
    with open(args.run / "metrics.jsonl", "a", encoding="utf-8") as log:
        for epoch in range(start, args.epochs):
            model.train()
            data.epoch = epoch
            t0, seen, total = time.time(), 0, 0.0
            if use_amp:
                torch.cuda.reset_peak_memory_stats()
            for x, y in loader:
                x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
                opt.zero_grad(set_to_none=True)
                with torch.autocast(device.type, enabled=use_amp):
                    loss = loss_fn(model(x), y, args.pos_weight, args.dice_weight)
                scaler.scale(loss).backward()
                scaler.step(opt)
                scaler.update()
                seen += 1
                total += loss.item()
            sched.step()
            row = {
                "epoch": epoch,
                "loss": total / max(seen, 1),
                "train_seconds": round(time.time() - t0, 1),
                "seconds_per_batch": round((time.time() - t0) / max(seen, 1), 3),
                "peak_gpu_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2) if use_amp else 0,
            }
            if (epoch + 1) % args.val_every == 0 or epoch + 1 == args.epochs:
                t1 = time.time()
                row["val"] = validate(model, val_tiles, args.cache, stats, device, args.crop)
                row["val_seconds"] = round(time.time() - t1, 1)
                if row["val"]["mean_event_f1"] > best:
                    best = row["val"]["mean_event_f1"]
                    torch.save(
                        {
                            "model": model.state_dict(),
                            "threshold": row["val"]["threshold"],
                            "epoch": epoch,
                            "window": args.crop,
                            "encoder": args.encoder,
                        },
                        args.run / "best.pt",
                    )
            torch.save(
                {
                    "model": model.state_dict(),
                    "opt": opt.state_dict(),
                    "sched": sched.state_dict(),
                    "scaler": scaler.state_dict(),
                    "epoch": epoch,
                    "best": best,
                },
                last,
            )
            log.write(json.dumps(row) + "\n")
            log.flush()
            print(row, flush=True)
            if args.max_hours and (time.time() - began) / 3600 >= args.max_hours:
                print("time budget reached; rerun the same command to continue", flush=True)
                break


if __name__ == "__main__":
    main()
