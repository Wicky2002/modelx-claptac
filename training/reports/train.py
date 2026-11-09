"""Train the report transformer. Rerunning with the same --run continues from the last epoch.

    python -m training.reports.train --data <unpacked news folder> --run <run dir>

Only the training and validation articles are read for scoring. Test articles are scored separately, once.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import numpy as np
import torch
from transformers import AutoTokenizer

from training.reports.data import load
from training.reports.model import NAME, ReportModel, predict, tokenize, truth
from training.reports.scores import decide, fit_thresholds, report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--epochs", type=int, default=4)
    p.add_argument("--articles", type=int, default=2, help="articles per batch")
    p.add_argument("--accumulate", type=int, default=4, help="batches per optimiser step")
    p.add_argument("--lr", type=float, default=2e-5)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--max-hours", type=float, default=0, help="stop cleanly after this; 0 = no limit")
    p.add_argument("--limit-train", type=int, default=0, help="use only N articles (speed test)")
    p.add_argument("--limit-val", type=int, default=0, help="use only N articles (speed test)")
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

    data = load(args.data)
    train = data["train"][: args.limit_train or None]
    val = data["val"][: args.limit_val or None]
    val_truth = truth(val)
    tokenizer = AutoTokenizer.from_pretrained(NAME)
    model = ReportModel().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    scaler = torch.amp.GradScaler(device.type, enabled=use_amp)
    bce = torch.nn.functional.binary_cross_entropy_with_logits

    start, best = 0, -1.0
    last = args.run / "last.pt"
    if last.exists():
        state = torch.load(last, map_location=device, weights_only=True)
        model.load_state_dict(state["model"])
        opt.load_state_dict(state["opt"])
        scaler.load_state_dict(state["scaler"])
        start, best = state["epoch"] + 1, state["best"]
        print(f"continuing from epoch {start}", flush=True)

    began = time.time()
    with open(args.run / "metrics.jsonl", "a", encoding="utf-8") as log:
        for epoch in range(start, args.epochs):
            model.train()
            order = list(range(len(train)))
            random.Random(f"{args.seed}-{epoch}").shuffle(order)
            t0, total, steps = time.time(), 0.0, 0
            opt.zero_grad(set_to_none=True)
            for i in range(0, len(order), args.articles):
                part = [train[k] for k in order[i : i + args.articles]]
                ids, mask, owners = tokenize(tokenizer, part, device)
                event_y = torch.from_numpy(np.stack([a.event for a in part])).float().to(device)
                sentence_y = (
                    torch.from_numpy(
                        np.concatenate([np.stack([a.location, a.impact], 1) for a in part])
                    )
                    .float()
                    .to(device)
                )
                with torch.autocast(device.type, enabled=use_amp):
                    event, sentence = model(ids, mask, owners, len(part))
                    loss = bce(event, event_y) + bce(sentence, sentence_y)
                scaler.scale(loss / args.accumulate).backward()
                steps += 1
                total += loss.item()
                if steps % args.accumulate == 0:
                    scaler.step(opt)
                    scaler.update()
                    opt.zero_grad(set_to_none=True)
            scores = predict(model, tokenizer, val, device)
            thresholds = fit_thresholds(scores, val_truth)
            summary = report(decide(scores, thresholds), val_truth)
            objective = float(
                np.mean(
                    [
                        summary["macro_f1_hazards"],
                        summary["location_sentences"]["f1"],
                        summary["impact_sentences"]["f1"],
                    ]
                )
            )
            row = {
                "epoch": epoch,
                "loss": total / max(steps, 1),
                "seconds": round(time.time() - t0, 1),
                "objective": objective,
                "val": summary,
            }
            if objective > best:
                best = objective
                torch.save(
                    {"model": model.state_dict(), "thresholds": thresholds, "epoch": epoch},
                    args.run / "best.pt",
                )
            torch.save(
                {
                    "model": model.state_dict(),
                    "opt": opt.state_dict(),
                    "scaler": scaler.state_dict(),
                    "epoch": epoch,
                    "best": best,
                },
                last,
            )
            log.write(json.dumps(row) + "\n")
            log.flush()
            print({k: row[k] for k in ("epoch", "loss", "seconds", "objective")}, flush=True)
            if args.max_hours and (time.time() - began) / 3600 >= args.max_hours:
                print("time budget reached; rerun the same command to continue", flush=True)
                break


if __name__ == "__main__":
    main()
