import json
import sys

import numpy as np
import pytest

from training.flood import evaluate
from training.flood.data import DB_MAX, DB_MIN, IGNORE


def write_tile(cache, name, vv, y):
    vv = np.array(vv, dtype=np.float16)
    x = np.stack([vv, vv, np.zeros_like(vv), np.zeros_like(vv), np.zeros_like(vv)])
    np.save(cache / f"{name}.x.npy", x)
    np.save(cache / f"{name}.y.npy", np.array(y, dtype=np.uint8))


def test_darker_radar_scores_higher_and_threshold_maps_back_to_db():
    water, land = evaluate.vv_score(np.array([-25.0, -8.0]))
    assert water > land
    assert evaluate.vv_score(np.array([DB_MIN]))[0] == 1.0
    assert evaluate.vv_score(np.array([DB_MAX]))[0] == 0.0
    score = float(evaluate.vv_score(np.array([-18.0]))[0])
    assert evaluate.score_to_db(score) == pytest.approx(-18.0)


def test_baseline_separates_water_and_ignores_no_data(tmp_path):
    write_tile(tmp_path, "a", [[-25.0, -8.0], [-26.0, -30.0]], [[1, 0], [1, IGNORE]])
    write_tile(tmp_path, "b", [[-24.0, -7.0]], [[1, 0]])
    by_event = evaluate.score_tiles([("E1", "a"), ("E2", "b")], tmp_path, evaluate.baseline_scorer)
    assert set(by_event) == {"E1", "E2"}
    assert by_event["E1"].pos.sum() + by_event["E1"].neg.sum() == 3
    threshold = evaluate.pooled_best_threshold(by_event)
    assert by_event["E1"].scores_at(threshold)["f1"] == 1.0
    assert by_event["E2"].scores_at(threshold)["f1"] == 1.0


def run_cli(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["evaluate", *args])
    evaluate.main()


def test_test_split_cannot_be_scored_twice_or_without_the_unet(tmp_path, monkeypatch):
    cache, run = tmp_path / "cache", tmp_path / "run"
    cache.mkdir()
    run.mkdir()
    (cache / "manifest.json").write_text(
        json.dumps({"failed": [], "stats": {}, "splits": {"val": [], "test": []}}), encoding="utf-8"
    )
    common = ["--cache", str(cache), "--run", str(run), "--split", "test"]
    with pytest.raises(SystemExit):
        run_cli(monkeypatch, *common, "--baseline-only")
    (run / "report_test.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        run_cli(monkeypatch, *common)
    assert (run / "report_test.json").read_text(encoding="utf-8") == "{}"
