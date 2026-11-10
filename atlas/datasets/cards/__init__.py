"""Dataset cards for the training data (proposal section 5.1).  (Owner: Dinuka)

Each dataset has one YAML file here. ``load_cards`` validates all of them, so a card with a missing
field fails the tests rather than reaching a reader. The raw data stays outside git.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

CARDS_DIR = Path(__file__).resolve().parent
SPLITS_DIR = CARDS_DIR.parents[2] / "data" / "splits"


class DatasetCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    name: str
    origin: str
    version: str
    doi: str | None
    url: str
    licence: str
    licence_source: str
    coverage: str
    variables: list[str]
    label_meaning: str
    missingness: str
    permitted_use: str
    limits: list[str]
    file: str
    size_bytes: int
    sha256: str
    verified: bool
    verification: str
    split_file: str


def load_cards() -> list[DatasetCard]:
    cards = []
    for path in sorted(CARDS_DIR.glob("*.yaml")):
        cards.append(DatasetCard(**yaml.safe_load(path.read_text(encoding="utf-8"))))
    return cards
