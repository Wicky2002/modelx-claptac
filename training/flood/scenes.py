"""Run a trained flood model over Sentinel-1 scenes of one place and export a flood layer per pass.

    python -m training.flood.scenes --scenes <dir> --cache <cache> --run <run dir> --out <dir>

<dir> holds s1/*.tif (VV and VH linear power, tagged with acquisition, orbit and product), dem.tif and
jrc/ (Global Surface Water occurrence tiles). Each layer is 0 dry, 1 flood, 255 no data, and carries its
acquisition time, so a replay can refuse to use it before the satellite actually passed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from training.flood.data import IGNORE, normalise, to_db
from training.flood.water import water_channel


def channels(vv: np.ndarray, vh: np.ndarray, dem: np.ndarray, occurrence: np.ndarray):
    """The six training channels for a scene without hydrography, and which pixels have valid radar."""
    invalid = ~np.isfinite(vv) | ~np.isfinite(vh) | ~np.isfinite(dem) | ((vv == 0) & (vh == 0))
    good = dem[np.isfinite(dem)]
    median = float(np.median(good)) if good.size else 0.0
    rel = np.clip(np.nan_to_num(dem - median, nan=0.0) / 100.0, -5, 5)
    none = np.zeros_like(rel)
    x = np.stack(
        [
            to_db(np.nan_to_num(vv, nan=0.0)),
            to_db(np.nan_to_num(vh, nan=0.0)),
            rel,
            none,  # hydrography
            none,  # hydrography present: no
            water_channel(occurrence),
        ]
    ).astype(np.float32)
    return x, ~invalid


def flood_layer(probability: np.ndarray, threshold: float, valid: np.ndarray) -> np.ndarray:
    layer = (probability >= threshold).astype(np.uint8)
    layer[~valid] = IGNORE
    return layer


def new_water_km2(layer: np.ndarray, permanent: np.ndarray, pixel_m2: float) -> float:
    """Flood outside permanent water. Rivers and reservoirs that are always wet are not new flooding."""
    return float(((layer == 1) & (permanent == 0)).sum()) * pixel_m2 / 1e6


def _read_scene(path: Path, dem_path: Path, jrc_dir: Path):
    import rasterio
    from rasterio.coords import BoundingBox
    from rasterio.warp import Resampling, reproject, transform_bounds

    from training.flood.water import read_occurrence

    with rasterio.open(path) as src:
        vv, vh = src.read(1), src.read(2)
        profile, tags = src.profile, src.tags()
        shape, transform, crs, bounds = src.shape, src.transform, src.crs, src.bounds
    dem = np.full(shape, np.nan, dtype=np.float32)
    with rasterio.open(dem_path) as src:
        reproject(
            rasterio.band(src, 1),
            dem,
            dst_transform=transform,
            dst_crs=crs,
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
    # read_occurrence finds JRC tiles from degrees; these scenes are in UTM.
    degrees = BoundingBox(*transform_bounds(crs, "EPSG:4326", *bounds))
    occurrence = read_occurrence(jrc_dir, shape, transform, crs, degrees)
    return vv, vh, dem, occurrence, profile, tags


def main() -> None:
    import rasterio
    import torch

    from training.flood.model import FloodUNet, predict_tile

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--scenes", type=Path, required=True)
    p.add_argument("--cache", type=Path, required=True, help="for the training radar statistics")
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    stats = json.loads((args.cache / "manifest.json").read_text(encoding="utf-8"))["stats"]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    state = torch.load(args.run / "best.pt", map_location=device, weights_only=True)
    model = FloodUNet(pretrained=False).to(device)
    model.load_state_dict(state["model"])
    model.eval()

    rows = []
    for path in sorted((args.scenes / "s1").glob("*.tif")):
        vv, vh, dem, occurrence, profile, tags = _read_scene(
            path, args.scenes / "dem.tif", args.scenes / "jrc"
        )
        x, valid = channels(vv, vh, dem, occurrence)
        probability = predict_tile(model, normalise(x, stats), device, window=state["window"])
        layer = flood_layer(probability, state["threshold"], valid)
        area = abs(profile["transform"].a * profile["transform"].e)
        row = {
            "acquired": tags["acquisition"],
            "orbit": tags["orbit"],
            "product": tags["product"],
            "flood_km2_outside_permanent_water": round(new_water_km2(layer, x[5], area), 2),
            "valid_fraction": round(float(valid.mean()), 4),
            "vv_db_median": round(float(np.median(x[0][valid])), 2),
            "vh_db_median": round(float(np.median(x[1][valid])), 2),
        }
        stem = tags["acquisition"][:19].replace(":", "").replace("-", "")
        target = args.out / f"flood_{stem}_{tags['orbit']}.tif"
        out_profile = {**profile, "count": 1, "dtype": "uint8", "nodata": IGNORE, "predictor": 1}
        with rasterio.open(target, "w", **out_profile) as dst:
            dst.write(layer, 1)
            dst.update_tags(
                acquisition=tags["acquisition"],
                orbit=tags["orbit"],
                product=tags["product"],
                model_run=args.run.name,
                best_epoch=str(state["epoch"]),
                threshold=str(state["threshold"]),
                values="0 dry, 1 flood, 255 no data",
            )
        rows.append({**row, "layer": target.name})
        print(rows[-1], flush=True)
    (args.out / "summary.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
