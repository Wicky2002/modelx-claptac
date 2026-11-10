import random

import pytest

from training.flood.search import (
    CURRENT,
    SPACE,
    child,
    decode,
    encode,
    first_generation,
    fitness,
    next_generation,
)


def test_decode_reverses_encode():
    for name, value in decode(encode(CURRENT)).items():
        assert value == pytest.approx(CURRENT[name])


def test_ends_of_a_gene_are_the_ends_of_its_range():
    low, high = decode([0.0] * len(SPACE)), decode([1.0] * len(SPACE))
    for name, (lower, upper, _) in SPACE.items():
        assert low[name] == pytest.approx(lower) and high[name] == pytest.approx(upper)


def test_first_generation_includes_todays_settings():
    genomes = first_generation(6, random.Random(1))
    assert len(genomes) == 6 and genomes[0] == encode(CURRENT)


def test_children_stay_in_range_and_are_repeatable():
    a, b = [0.0] * len(SPACE), [1.0] * len(SPACE)
    assert all(0 <= g <= 1 for _ in range(50) for g in child(a, b, random.Random(_)))
    scored = [([0.1] * len(SPACE), 0.1), ([0.9] * len(SPACE), 0.9)]
    assert next_generation(scored, 3, random.Random(5)) == next_generation(scored, 3, random.Random(5))


def test_fitness_averages_only_the_last_checks():
    rows = [{"loss": 1}] + [{"val": {"mean_event_f1": v}} for v in (0.9, 0.2, 0.3, 0.4)]
    assert fitness(rows) == pytest.approx(0.3)
    with pytest.raises(ValueError):
        fitness([{"loss": 1}])
