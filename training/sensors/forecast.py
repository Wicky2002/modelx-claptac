"""Forecast a Mawiongrim sensor reading a few hours ahead: LightGBM against "next equals last".

    python -m training.sensors.forecast --csv <mawiongrim.csv> --out <dir>

The file has no landslide events, so this is sensor forecasting, not landslide warning (§8, §10).
Splits come from data/splits/mawiongrim.json (by time). Features are built inside each split, so no
window crosses a split boundary. Model settings are fixed, and the test split is scored once.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

SPLITS = Path(__file__).resolve().parents[2] / "data/splits/mawiongrim.json"
TARGETS = {"Inc 30m up": "tilt (inclinometer, 30 m up)", "Water level": "water level"}
HORIZONS = (1, 3, 6)
LAGS = 6


def load(csv: Path) -> pd.DataFrame:
    frame = pd.read_csv(csv)
    frame.columns = [c.strip() for c in frame.columns]
    frame = frame.drop(columns=[c for c in frame.columns if c.startswith("Unnamed")])
    frame = frame.rename(columns={"Inc30mup": "Inc 30m up"})
    frame["Timestamp"] = pd.to_datetime(frame["Timestamp"])
    return frame.set_index("Timestamp").sort_index()


def split(frame: pd.DataFrame, splits: dict) -> dict[str, pd.DataFrame]:
    return {
        name: frame.loc[span["first"] : span["last"]] for name, span in splits["splits"].items()
    }


def features(part: pd.DataFrame, target: str, horizon: int):
    """Lags of every sensor and recent change of the target; y is the target `horizon` hours on."""
    cols = {}
    for name in part.columns:
        for lag in range(LAGS):
            cols[f"{name} t-{lag}"] = part[name].shift(lag)
    cols["change 1h"] = part[target].diff(1)
    cols["change 3h"] = part[target].diff(3)
    cols["hour"] = part.index.hour
    x = pd.DataFrame(cols, index=part.index)
    y = part[target].shift(-horizon)
    keep = x.notna().all(axis=1) & y.notna()
    return x[keep], y[keep], part[target][keep]


def scores(truth: np.ndarray, guess: np.ndarray) -> dict:
    error = guess - truth
    return {
        "mae": round(float(np.abs(error).mean()), 4),
        "rmse": round(float(np.sqrt((error**2).mean())), 4),
    }


def run(frame: pd.DataFrame, splits: dict, seed: int = 0) -> list[dict]:
    import lightgbm as lgb

    parts = split(frame, splits)
    rows = []
    for target, meaning in TARGETS.items():
        for horizon in HORIZONS:
            built = {name: features(p, target, horizon) for name, p in parts.items()}
            x_train, y_train, _ = built["train"]
            # Predict the change from now, which keeps the model honest against persistence.
            model = lgb.LGBMRegressor(
                n_estimators=300,
                learning_rate=0.03,
                num_leaves=15,
                min_child_samples=10,
                subsample=0.8,
                subsample_freq=1,
                colsample_bytree=0.8,
                random_state=seed,
                verbose=-1,
            )
            model.fit(x_train, y_train - x_train[f"{target} t-0"])
            row = {"target": target, "meaning": meaning, "horizon_h": horizon}
            for name in ("val", "test"):
                x, y, now = built[name]
                guess = now.to_numpy() + model.predict(x)
                row[name] = {
                    "rows": int(len(y)),
                    "persistence": scores(y.to_numpy(), now.to_numpy()),
                    "lightgbm": scores(y.to_numpy(), guess),
                }
            rows.append(row)
    return rows


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--csv", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / "forecast_report.json"
    if target.exists():
        raise SystemExit(f"{target} exists: the test split is scored once.")
    splits = json.loads(SPLITS.read_text(encoding="utf-8"))
    rows = run(load(args.csv), splits, args.seed)
    target.write_text(json.dumps({"seed": args.seed, "results": rows}, indent=2), encoding="utf-8")
    for r in rows:
        print(r["target"], r["horizon_h"], "val", r["val"], "test", r["test"])


if __name__ == "__main__":
    main()
