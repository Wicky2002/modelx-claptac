"""Build the committed split files, before any tiling or windowing.  (Owner: Dinuka)

    python -m atlas.datasets splits --mmflood <mmflood/> --innova <folder with the other three>

The same input always gives the same split. Everything from one flood event, or one duplicated
article, stays on one side, so a score cannot come from having seen the same event in training.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from atlas.datasets.cards import SPLITS_DIR

SEED = 42
csv.field_size_limit(10_000_000)


def _order(key: str) -> str:
    return hashlib.sha256(f"{SEED}:{key}".encode()).hexdigest()


def assign_groups(sizes: dict[str, int], test: float, val: float) -> dict[str, str]:
    """Give whole groups to test, then val, then train, in a fixed pseudo-random order."""
    total = sum(sizes.values())
    used = {"test": 0, "val": 0}
    out = {}
    for group in sorted(sizes, key=_order):
        if used["test"] < test * total:
            out[group] = "test"
        elif used["val"] < val * total:
            out[group] = "val"
        else:
            out[group] = "train"
        if out[group] != "train":
            used[out[group]] += sizes[group]
    return out


def mmflood(root: Path) -> dict:
    meta = json.loads((root / "activations.json").read_text(encoding="utf-8"))
    tiles = Counter(p.parent.parent.name.split("-")[0] for p in root.glob("activations/*/s1_raw/*.tif"))
    events: dict[str, list[str]] = defaultdict(list)
    tile_counts: Counter = Counter()
    for event, info in sorted(meta.items()):
        events[info["subset"]].append(event)
        tile_counts[info["subset"]] += tiles[event]
    return {
        "dataset": "mmflood",
        "unit": "event",
        "method": "MMFlood's own event split, from activations.json",
        "tiles": dict(tile_counts),
        "splits": dict(events),
    }


def _event_key(name: str) -> str:
    return " ".join(name.lower().split())


def aifloodsense(archive: Path) -> dict:
    rows = []
    with zipfile.ZipFile(archive) as z:
        for part in ("train", "test"):
            text = z.read(f"AIFloodSense/AIFloodSense-{part}.csv").decode("utf-8", "replace")
            rows += [{**row, "original": part} for row in csv.DictReader(io.StringIO(text))]
    sizes = Counter(_event_key(r["FLOOD_NAME"]) for r in rows)
    assigned = assign_groups(sizes, test=0.2, val=0.1)
    splits: dict[str, list[str]] = defaultdict(list)
    events: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        side = assigned[_event_key(row["FLOOD_NAME"])]
        splits[side].append(row["IMAGE_ID"])
        events[side].add(_event_key(row["FLOOD_NAME"]))
    shared = {_event_key(r["FLOOD_NAME"]) for r in rows if r["original"] == "train"} & {
        _event_key(r["FLOOD_NAME"]) for r in rows if r["original"] == "test"
    }
    leaked = sum(1 for r in rows if r["original"] == "test" and _event_key(r["FLOOD_NAME"]) in shared)
    return {
        "dataset": "aifloodsense",
        "unit": "image",
        "seed": SEED,
        "method": "Re-split by flood name, so no name appears on two sides",
        "note": (
            f"{leaked} of the published test images share a flood name with the published training "
            "set. Rows are grouped by name alone because some events carry two years in the metadata."
        ),
        "events": {side: sorted(names) for side, names in sorted(events.items())},
        "splits": {side: sorted(ids) for side, ids in sorted(splits.items())},
    }


def disaster_news(archive: Path) -> dict:
    sentences: dict[int, list[str]] = defaultdict(list)
    with zipfile.ZipFile(archive) as z:
        name = "doc_id_and_sentences_for_event_location_impact.csv"
        text = z.read(name).decode("utf-8", "replace")
    for row in csv.DictReader(io.StringIO(text, newline="")):
        sentences[int(row["doc_id"])].append(row["sentence"])
    groups: dict[str, list[int]] = defaultdict(list)
    for doc, parts in sentences.items():
        body = re.sub(r"[^a-z0-9]+", " ", " ".join(parts).lower()).strip()
        groups[hashlib.sha256(body.encode()).hexdigest()].append(doc)
    assigned = assign_groups({g: len(d) for g, d in groups.items()}, test=0.1, val=0.1)
    splits: dict[str, list[int]] = defaultdict(list)
    for group, docs in groups.items():
        splits[assigned[group]] += docs
    return {
        "dataset": "disaster-news",
        "unit": "article",
        "seed": SEED,
        "method": "Split by article. Articles with identical text stay together.",
        "note": f"{len(sentences) - len(groups)} articles duplicate the text of another article.",
        "splits": {side: sorted(docs) for side, docs in sorted(splits.items())},
    }


def mawiongrim(path: Path) -> dict:
    with open(path, encoding="utf-8", newline="") as handle:
        stamps = sorted(row["Timestamp"] for row in csv.DictReader(handle))
    train_end, val_end = int(len(stamps) * 0.7), int(len(stamps) * 0.85)
    parts = {"train": stamps[:train_end], "val": stamps[train_end:val_end], "test": stamps[val_end:]}
    return {
        "dataset": "mawiongrim",
        "unit": "hourly row",
        "method": "By time: the first 70% of hours, the next 15%, the last 15%",
        "note": "Windows that cross a boundary must be dropped by whoever builds the features.",
        "splits": {
            side: {"first": rows[0], "last": rows[-1], "rows": len(rows)} for side, rows in parts.items()
        },
    }


def save_all(mmflood_root: Path, innova: Path) -> list[Path]:
    built = [
        mmflood(mmflood_root),
        aifloodsense(innova / "AIFloodSense.zip"),
        disaster_news(innova / "event_location_impact.zip"),
        mawiongrim(innova / "mawiongrim.csv"),
    ]
    SPLITS_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    for split in built:
        path = SPLITS_DIR / f"{split['dataset']}.json"
        path.write_text(json.dumps(split, sort_keys=True) + "\n", encoding="utf-8")
        paths.append(path)
    return paths
