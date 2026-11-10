"""Compare the keyword rules and the transformer on the same articles.

    python -m training.reports.evaluate --data <folder> --run <run dir> --split val
    python -m training.reports.evaluate --data <folder> --run <run dir> --split test

The transformer's thresholds come from validation data. A test report is written once: a second
attempt stops before reading any test article. Results are English-only, like the dataset.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from training.reports.data import load
from training.reports.keywords import predict as keyword_predict
from training.reports.scores import Outputs, decide, report


def truth_of(articles) -> Outputs:
    from training.reports.model import truth

    return truth(articles)


def transformer_reports(run: Path, val, articles, gold: Outputs) -> dict:
    """The transformer alone, and the hybrid whose per-hazard rules are chosen on validation."""
    import torch
    from transformers import AutoTokenizer

    from training.reports import hybrid
    from training.reports.model import NAME, ReportModel, predict

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    state = torch.load(run / "best.pt", map_location=device, weights_only=True)
    model = ReportModel().to(device)
    model.load_state_dict(state["model"])
    tokenizer = AutoTokenizer.from_pretrained(NAME)
    val_scores = predict(model, tokenizer, val, device)
    rules = hybrid.fit(keyword_predict(val), val_scores, truth_of(val))
    scores = val_scores if articles is val else predict(model, tokenizer, articles, device)
    sentence = {"location": state["thresholds"]["location"], "impact": state["thresholds"]["impact"]}
    return {
        "transformer": {
            **report(decide(scores, state["thresholds"]), gold),
            "best_epoch": state["epoch"],
        },
        "hybrid": {
            **report(hybrid.decide(keyword_predict(articles), scores, rules, sentence), gold),
            "rules": rules,
        },
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--split", choices=["val", "test"], required=True)
    p.add_argument("--baseline-only", action="store_true", help="skip the transformer; validation only")
    args = p.parse_args()

    out = args.run / f"report_{args.split}.json"
    if args.split == "test":
        if args.baseline_only:
            p.error("the test articles are scored once, with both models together")
        if out.exists():
            p.error(f"{out} already exists; the test articles have been scored")

    data = load(args.data)
    articles = data[args.split]
    gold = truth_of(articles)
    summary = {
        "split": args.split,
        "articles": len(articles),
        "language": "English-only",
        "keywords": report(keyword_predict(articles), gold),
    }
    if not args.baseline_only:
        summary.update(transformer_reports(args.run, data["val"], articles, gold))

    args.run.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    for name in ("keywords", "transformer", "hybrid"):
        if name in summary:
            s = summary[name]
            print(
                f"{name}: macro-F1 {s['macro_f1_hazards']:.3f}"
                f" location P {s['location_sentences']['precision']:.3f}"
                f" R {s['location_sentences']['recall']:.3f}"
                f" impact P {s['impact_sentences']['precision']:.3f}"
                f" R {s['impact_sentences']['recall']:.3f}",
                flush=True,
            )


if __name__ == "__main__":
    main()
