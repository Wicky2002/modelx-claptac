"""MMFlood: prepare tiles once, then read random crops quickly.

    python -m training.flood.data --data-root <path to mmflood/> --jrc <jrc dir> --cache <cache dir>

Each tile becomes two uncompressed arrays, so a crop reads only the pixels it needs.

    x: VV dB, VH dB, relative elevation, hydrography, hydrography-present, permanent water
    y: 0 dry, 1 flood, 255 no data (ignored by the loss and the scores)

Splits come from MMFlood's own ``activations.json``, which separates whole events (proposal section 6).
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np

IGNORE = 255
DB_MIN, DB_MAX = -40.0, 10.0
CHANNELS = 6


def to_db(power: np.ndarray) -> np.ndarray:
    """MMFlood's Sentinel-1 bands are linear power. Zero and tiny values are floored at DB_MIN."""
    return np.clip(10 * np.log10(np.maximum(power, 10 ** (DB_MIN / 10))), DB_MIN, DB_MAX)


def tiles_by_split(data_root: Path) -> dict[str, list[tuple[str, str]]]:
    """{split: [(event, tile name)]}, sorted so that every run sees the same order."""
    meta = json.loads((data_root / "activations.json").read_text(encoding="utf-8"))
    out: dict[str, list[tuple[str, str]]] = {"train": [], "val": [], "test": []}
    for path in sorted((data_root / "activations").glob("*/s1_raw/*.tif")):
        event = path.parent.parent.name.split("-")[0]
        out[meta[event]["subset"]].append((event, path.stem))
    return out


def prepare_tile(data_root: Path, name: str, cache: Path, jrc_dir: Path) -> None:
    import rasterio
    import rasterio.enums

    from training.flood.water import read_occurrence, water_channel

    aoi = "-".join(name.split("-")[:2])
    base = data_root / "activations" / aoi

    def read(kind: str, band: int | None = None) -> np.ndarray:
        with rasterio.open(base / kind / f"{name}.tif") as src:
            return src.read() if band is None else src.read(band)

    s1 = read("s1_raw")
    dem = read("DEM", 1).astype(np.float32)
    mask = read("mask", 1)
    hydro_path = base / "hydro" / f"{name}.tif"
    if hydro_path.exists():
        # MMFlood's hydrography covers the same bounds as the radar on a slightly different pixel
        # grid (a few pixels off in most tiles), so it is resampled onto the radar grid.
        with rasterio.open(hydro_path) as src:
            hydro = src.read(1, out_shape=mask.shape, resampling=rasterio.enums.Resampling.nearest)
    else:
        hydro = np.zeros_like(mask)
    if not s1.shape[1:] == dem.shape == mask.shape:
        raise ValueError(f"{name}: layers have different shapes")

    # A pixel with no radar return in both bands is treated as no data, like a NaN.
    invalid = ~np.isfinite(s1).all(0) | ~np.isfinite(dem) | ((s1[0] == 0) & (s1[1] == 0))
    vv = to_db(np.nan_to_num(s1[0], nan=0.0))
    vh = to_db(np.nan_to_num(s1[1], nan=0.0))
    # Elevation relative to the tile: what matters for flooding is the local terrain, and this also
    # transfers to places whose absolute height differs from the training events.
    good_dem = dem[np.isfinite(dem)]
    median = float(np.median(good_dem)) if good_dem.size else 0.0
    rel = np.clip(np.nan_to_num(dem - median, nan=0.0) / 100.0, -5, 5)
    present = np.full_like(rel, 1.0 if hydro_path.exists() else 0.0)
    with rasterio.open(base / "s1_raw" / f"{name}.tif") as src:
        water = water_channel(read_occurrence(jrc_dir, mask.shape, src.transform, src.crs, src.bounds))
    x = np.stack([vv, vh, rel, (hydro > 0).astype(np.float32), present, water]).astype(np.float16)
    y = (mask > 0).astype(np.uint8)
    y[invalid] = IGNORE

    np.save(cache / f"{name}.x.npy", x)
    np.save(cache / f"{name}.y.npy", y)


def fit_stats(tiles: list[tuple[str, str]], cache: Path, seed: int = 42) -> dict:
    """Mean and std of the radar bands, from training pixels only."""
    rng = np.random.default_rng(seed)
    vv, vh = [], []
    for _, name in tiles:
        x = np.load(cache / f"{name}.x.npy", mmap_mode="r")
        y = np.load(cache / f"{name}.y.npy", mmap_mode="r")
        keep = np.flatnonzero(np.asarray(y).ravel() != IGNORE)
        if keep.size == 0:
            continue
        pick = rng.choice(keep, size=min(2000, keep.size), replace=False)
        vv.append(np.asarray(x[0]).ravel()[pick].astype(np.float32))
        vh.append(np.asarray(x[1]).ravel()[pick].astype(np.float32))
    a, b = np.concatenate(vv), np.concatenate(vh)
    return {"mean": [float(a.mean()), float(b.mean())], "std": [float(a.std()), float(b.std())]}


def normalise(x: np.ndarray, stats: dict) -> np.ndarray:
    x = x.astype(np.float32)
    for band in (0, 1):
        x[band] = (x[band] - stats["mean"][band]) / stats["std"][band]
    return x


class CropDataset:
    """Random training crops. Half are centred on a flood pixel because only about 3% of pixels flood."""

    def __init__(
        self, tiles, cache: Path, stats: dict, crop: int, per_tile: int, seed: int, flood_crops=0.5
    ) -> None:
        self.tiles, self.cache, self.stats, self.crop = tiles, Path(cache), stats, crop
        self.per_tile, self.seed, self.flood_crops = per_tile, seed, flood_crops
        self.epoch = 0

    def __len__(self) -> int:
        return len(self.tiles) * self.per_tile

    def __getitem__(self, index: int):
        rng = random.Random(f"{self.seed}-{self.epoch}-{index}")
        _, name = self.tiles[index % len(self.tiles)]
        x = np.load(self.cache / f"{name}.x.npy", mmap_mode="r")
        y = np.load(self.cache / f"{name}.y.npy", mmap_mode="r")
        height, width = y.shape
        size = self.crop
        top, left = rng.randint(0, height - size), rng.randint(0, width - size)
        if rng.random() < self.flood_crops:
            rows, cols = np.nonzero(np.asarray(y) == 1)
            if rows.size:
                i = rng.randrange(rows.size)
                top = int(np.clip(rows[i] - size // 2, 0, height - size))
                left = int(np.clip(cols[i] - size // 2, 0, width - size))
        cx = normalise(np.array(x[:, top : top + size, left : left + size]), self.stats)
        cy = np.array(y[top : top + size, left : left + size])
        if rng.random() < 0.5:
            cx, cy = cx[:, :, ::-1], cy[:, ::-1]
        if rng.random() < 0.5:
            cx, cy = cx[:, ::-1], cy[::-1]
        k = rng.randrange(4)
        cx, cy = np.rot90(cx, k, (1, 2)), np.rot90(cy, k)
        return cx.copy(), cy.astype(np.int64).copy()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--jrc", type=Path, required=True, help="tiles from training.flood.water")
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    splits = tiles_by_split(args.data_root)
    counts = {k: len(v) for k, v in splits.items()}
    print("tiles", counts, flush=True)
    failed = []
    done = 0
    for tiles in splits.values():
        for _, name in tiles:
            try:
                prepare_tile(args.data_root, name, args.cache, args.jrc)
            except Exception as err:  # keep going, then report every bad tile at the end
                failed.append(f"{name}: {err}")
            done += 1
            if done % 200 == 0:
                print(done, flush=True)
    bad = {f.split(":")[0] for f in failed}
    train = [t for t in splits["train"] if t[1] not in bad]
    stats = fit_stats(train, args.cache)
    summary = {"counts": counts, "stats": stats, "failed": failed, "splits": splits}
    (args.cache / "manifest.json").write_text(json.dumps(summary), encoding="utf-8")
    print("stats", stats, "failed", len(failed), failed[:5], flush=True)


if __name__ == "__main__":
    main()
