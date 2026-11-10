"""Keyword rules: the baseline the transformer has to beat. English only, like the dataset."""

from __future__ import annotations

import re

import numpy as np

from training.reports.data import HAZARDS, Article
from training.reports.scores import Outputs

WORDS = {
    "covid": r"covid|coronavirus|pandemic|lockdown",
    "flood": r"flood|inundat|deluge|waterlogg",
    "storm": r"storm|cyclone|typhoon|hurricane",
    "heavy rain": r"heavy rain|torrential|downpour|incessant rain|heavy showers|rainfall",
    "cloudburst": r"cloud\s?burst",
    "landslide": r"landslide|landslip|mudslide",
    "earthquake": r"earthquake|quake|tremor|seismic",
    "tsunami": r"tsunami",
}
PATTERNS = {name: re.compile(words, re.IGNORECASE) for name, words in WORDS.items()}
LOCATION = re.compile(r"\b(?:in|at|near|across|around|from)\s+(?:the\s+)?[A-Z][a-z]+")
IMPACT = re.compile(
    r"\b(?:killed|dead|deaths?|died|injured|missing|displaced|evacuat\w+|damaged?|destroyed|"
    r"homeless|stranded|affected|rescued|collapsed|submerged|casualt\w+|toll|infected|cases)\b",
    re.IGNORECASE,
)


def hazards_in(text: str) -> list[int]:
    return [1 if PATTERNS[name].search(text) else 0 for name in HAZARDS]


def predict(articles: list[Article]) -> Outputs:
    events, locations, impacts = [], [], []
    for article in articles:
        found = hazards_in(" ".join(article.sentences))
        events.append([1 if any(found) else 0, *found])
        locations += [1 if LOCATION.search(s) else 0 for s in article.sentences]
        impacts += [1 if IMPACT.search(s) else 0 for s in article.sentences]
    return Outputs(
        np.array(events, dtype=np.int64),
        np.array(locations, dtype=np.int64),
        np.array(impacts, dtype=np.int64),
    )
