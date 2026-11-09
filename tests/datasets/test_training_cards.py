import json

import pytest

from atlas.datasets.cards import SPLITS_DIR, DatasetCard, load_cards
from atlas.datasets.splits import assign_groups


def split_of(card):
    return json.loads((SPLITS_DIR / card.split_file).read_text(encoding="utf-8"))


def test_every_training_dataset_has_a_card_and_a_committed_split():
    cards = load_cards()
    assert {c.key for c in cards} == {"mmflood", "aifloodsense", "disaster-news", "mawiongrim"}
    for card in cards:
        assert set(split_of(card)["splits"]) == {"train", "val", "test"}
        assert len(card.sha256) == 64


def test_a_card_with_an_unknown_field_is_rejected():
    fields = load_cards()[0].model_dump()
    with pytest.raises(ValueError):
        DatasetCard(**fields, unexpected=1)


@pytest.mark.parametrize("key", ["mmflood", "aifloodsense", "disaster-news"])
def test_no_item_is_on_two_sides(key):
    card = next(c for c in load_cards() if c.key == key)
    parts = [set(v) for v in split_of(card)["splits"].values()]
    assert not (parts[0] & parts[1] or parts[0] & parts[2] or parts[1] & parts[2])


def test_mmflood_keeps_the_published_event_split():
    card = next(c for c in load_cards() if c.key == "mmflood")
    split = split_of(card)
    assert {k: len(v) for k, v in split["splits"].items()} == {"train": 54, "val": 7, "test": 34}
    assert split["tiles"] == {"train": 1242, "val": 120, "test": 386}


def test_no_flood_event_is_on_two_sides_of_aifloodsense():
    card = next(c for c in load_cards() if c.key == "aifloodsense")
    events = [set(v) for v in split_of(card)["events"].values()]
    assert not (events[0] & events[1] or events[0] & events[2] or events[1] & events[2])
    assert sum(len(v) for v in split_of(card)["splits"].values()) == 470


def test_news_covers_every_article():
    card = next(c for c in load_cards() if c.key == "disaster-news")
    ids = sorted(i for v in split_of(card)["splits"].values() for i in v)
    assert ids == list(range(7692))


def test_mawiongrim_sides_follow_time():
    card = next(c for c in load_cards() if c.key == "mawiongrim")
    s = split_of(card)["splits"]
    assert s["train"]["last"] < s["val"]["first"] <= s["val"]["last"] < s["test"]["first"]


def test_groups_stay_whole_and_the_result_repeats():
    sizes = {f"g{i}": (i % 5) + 1 for i in range(100)}
    first = assign_groups(sizes, test=0.2, val=0.1)
    assert first == assign_groups(dict(reversed(list(sizes.items()))), test=0.2, val=0.1)
    assert set(first) == set(sizes)
    assert set(first.values()) == {"train", "val", "test"}
