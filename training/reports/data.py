"""The disaster-news dataset, read with the committed article split.

Event bits, from the dataset's published description: event present, then the eight hazards in HAZARDS.
Location and impact are one bit per sentence for the first 40 sentences of an article.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HAZARDS = ["covid", "flood", "storm", "heavy rain", "cloudburst", "landslide", "earthquake", "tsunami"]
LABELS = ["event", *HAZARDS]
MAX_SENTENCES = 40
SPLIT_FILE = Path(__file__).resolve().parents[2] / "data" / "splits" / "disaster-news.json"
SENTENCES = "doc_id_and_sentences_for_event_location_impact.csv"


@dataclass
class Article:
    doc_id: int
    sentences: list[str]
    event: np.ndarray
    location: np.ndarray
    impact: np.ndarray


def read_sentences(path: Path) -> dict[int, list[str]]:
    csv.field_size_limit(10_000_000)
    out: dict[int, list[str]] = {}
    with open(path, encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            out.setdefault(int(row["doc_id"]), []).append(row["sentence"])
    return out


def load(data_dir: Path) -> dict[str, list[Article]]:
    import torch

    def tensor(name: str):
        return torch.load(data_dir / f"{name}.pt", weights_only=True)

    sentences = read_sentences(data_dir / SENTENCES)
    event, location, impact = (
        tensor("target_event_classes"),
        tensor("target_location_labels"),
        tensor("target_impact_labels"),
    )
    split = json.loads(SPLIT_FILE.read_text(encoding="utf-8"))["splits"]
    out: dict[str, list[Article]] = {}
    for side, docs in split.items():
        out[side] = []
        for doc in docs:
            kept = sentences[doc][:MAX_SENTENCES]
            out[side].append(
                Article(
                    doc,
                    kept,
                    event[doc].numpy().astype(np.int64),
                    location[doc][: len(kept)].numpy().astype(np.int64),
                    impact[doc][: len(kept)].numpy().astype(np.int64),
                )
            )
    return out
