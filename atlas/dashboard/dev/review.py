"""Read-only U4 adapters. No training imports, registry writes or A10 review events."""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt, model_validator

ROOT = Path(__file__).resolve().parents[3]
SAMPLES = Path(__file__).with_name("samples")
Count = Annotated[StrictInt, Field(ge=0)]
Finite = Annotated[float, Field(allow_inf_nan=False)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Provenance(Contract):
    dataset: str
    dataset_version: str | None = None
    split: str
    seed: int | None = None
    generated_at: AwareDatetime
    source: str


class LabelCount(Contract):
    label: str
    count: Count


class FloodPixels(Contract):
    flood: Count
    non_flood: Count
    ignored: Count = 0


class Bin(Contract):
    x: Finite
    y: Finite
    count: Annotated[StrictInt, Field(gt=0)]


class Relationship(Contract):
    x_label: str
    y_label: str
    x_unit: str | None = None
    y_unit: str | None = None
    method: str
    total_pairs: Count
    bins: list[Bin] = Field(max_length=2000)

    @model_validator(mode="after")
    def count_pairs(self):
        if sum(b.count for b in self.bins) != self.total_pairs:
            raise ValueError("bin counts must sum to total_pairs")
        return self


class Profile(Provenance):
    schema_version: Literal[1]
    label_unit: str = "items"
    labels: list[LabelCount] = Field(default_factory=list, max_length=200)
    flood_pixels: FloodPixels | None = None
    relationships: list[Relationship] = Field(default_factory=list, max_length=10)
    notes: list[str] = Field(default_factory=list)


class EvaluationSource(Contract):
    path: str
    dataset: str
    dataset_version: str | None = None
    model_version: str | None = None
    seed: int | None = None
    generated_at: AwareDatetime | None = None
    source: str


class Manifest(Contract):
    schema_version: Literal[1]
    profiles: list[str] = Field(default_factory=list, max_length=100)
    evaluations: list[EvaluationSource] = Field(default_factory=list, max_length=100)


def read_file(root: Path, name: str):
    """Only small files inside the configured directory, including after symlink resolution."""
    path = (root / name).resolve()
    if Path(name).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError("report must be inside its configured directory")
    with path.open("rb") as stream:
        data = stream.read(5_000_001)
    if len(data) > 5_000_000:
        raise ValueError("report too large")
    return data.decode("utf-8")


def finite_json(value):
    # D2 emits NaN for undefined metrics. Undefined is not a score of zero.
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: finite_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [finite_json(v) for v in value]
    return value


def evaluation(root, entry):
    raw = json.loads(read_file(root, entry.path))
    if raw.get("split") not in ("val", "test"):
        raise ValueError("unsupported evaluation split")
    tiles = raw.get("tiles")
    if type(tiles) is not int or tiles < 0:
        raise ValueError("invalid tile count")
    variants = []
    for name in ("baseline", "unet", "combined"):
        if name not in raw:
            continue
        group = raw[name]
        scores = group["all_pixels"]
        metrics = {k: scores.get(k) for k in ("iou", "f1", "precision", "recall")}
        metrics.update({k: group.get(k) for k in ("mean_event_iou", "mean_event_f1")})
        for value in metrics.values():
            if value is not None and (
                type(value) not in (int, float)
                or math.isinf(value)
                or (math.isfinite(value) and not 0 <= value <= 1)
            ):
                raise ValueError("invalid score")
        events = group.get("events")
        if type(events) is not int or events < 0:
            raise ValueError("invalid event count")
        threshold = scores.get("threshold")
        if threshold is not None and type(threshold) not in (int, float):
            raise ValueError("invalid threshold")
        variants.append(
            {"name": name, "metrics": metrics, "events": events, "threshold": threshold}
        )
    if not variants:
        raise ValueError("no supported D2 variants")
    return finite_json(
        {
            **entry.model_dump(mode="json", exclude={"path"}),
            "file": Path(entry.path).name,
            "split": raw["split"],
            "tiles": tiles,
            "variants": variants,
        }
    )


class DatasetCard(BaseModel):
    # D1 may add fields without breaking this read-side projection.
    key: str
    name: str
    version: str
    coverage: str
    variables: list[str]
    label_meaning: str
    missingness: str
    licence: str
    limits: list[str]
    verified: bool
    verification: str
    split_file: str


def dataset_cards(root, warnings):
    directory = root / "atlas/datasets/cards"
    cards = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            raw = yaml.safe_load(read_file(directory, path.name))
            checked = DatasetCard.model_validate(raw)
            card = checked.model_dump(exclude={"split_file"})
            card["splits"] = []
            if raw.get("split_file"):
                split = json.loads(read_file(root / "data/splits", raw["split_file"]))
                if split["dataset"] != card["key"]:
                    raise ValueError("split belongs to another dataset")
                for name, values in split["splits"].items():
                    count = len(values) if isinstance(values, list) else values["rows"]
                    if type(count) is not int or count < 0:
                        raise ValueError("invalid split count")
                    tiles = split.get("tiles", {}).get(name)
                    if tiles is not None and (type(tiles) is not int or tiles < 0):
                        raise ValueError("invalid tile count")
                    card["splits"].append(
                        {
                            "name": name,
                            "count": count,
                            "unit": split["unit"],
                            "tiles": split.get("tiles", {}).get(name),
                        }
                    )
            cards.append(card)
        except (OSError, ValueError, TypeError, KeyError, AttributeError, yaml.YAMLError):
            warnings.append(f"Could not read dataset card {path.name} or its split file.")
    return cards


def data_exploration(*, sample=False):
    if sample:
        return json.loads(read_file(SAMPLES, "data.json"))
    root = Path(os.environ.get("ATLAS_REVIEW_DATA_ROOT", ROOT))
    reports = Path(os.environ.get("ATLAS_REVIEW_REPORTS_DIR", root / "data/model-review"))
    warnings, profiles, evaluations = [], [], []
    cards = dataset_cards(root, warnings)
    if (reports / "index.json").exists():
        try:
            manifest = Manifest.model_validate_json(read_file(reports, "index.json"))
        except (OSError, ValueError):
            warnings.append("Could not read report index.json; check the U4 report contract.")
        else:
            for name in manifest.profiles:
                try:
                    profiles.append(
                        Profile.model_validate_json(read_file(reports, name)).model_dump(
                            mode="json"
                        )
                    )
                except (OSError, ValueError):
                    warnings.append(f"Could not read profile {Path(name).name}.")
            for entry in manifest.evaluations:
                try:
                    evaluations.append(evaluation(reports, entry))
                except (OSError, ValueError, TypeError, KeyError, AttributeError):
                    warnings.append(f"Could not read evaluation {Path(entry.path).name}.")
    return {
        "mode": "recorded",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "cards": cards,
        "profiles": profiles,
        "evaluations": evaluations,
        "warnings": warnings,
    }


def model_review(system, *, sample=False):
    if sample:
        return json.loads(read_file(SAMPLES, "models.json"))
    runtime = system.runtime
    registry, learning = getattr(runtime, "models", None), getattr(system, "learning", None)
    models = [m.model_dump(mode="json") for m in registry.list()] if registry else []
    reviews = []
    if learning:
        for name in sorted({m["name"] for m in models}):
            # review() publishes an event; these two methods only read.
            reviews.append(
                {
                    "name": name,
                    "drift": learning.drift(name),
                    "shadows": [
                        learning.shadow_summary(name, m["version"])
                        for m in models
                        if m["name"] == name and m["status"] == "shadow"
                    ],
                }
            )
    history = [
        json.loads(r[0])
        for r in runtime.db.connection.execute(
            "SELECT body FROM ledger WHERE kind='model' ORDER BY seq DESC LIMIT 200"
        )
    ]
    requests = [
        row
        for row in system.control.gateway.list_actions()
        if row["action"]["action_type"] in ("promote_model", "rollback_model")
    ][-100:]
    return finite_json(
        {
            "mode": "recorded",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "registry_available": registry is not None,
            "learning_available": learning is not None,
            "models": models,
            "reviews": reviews,
            "history": history,
            "requests": requests,
        }
    )
