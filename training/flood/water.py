"""JRC Global Surface Water occurrence: how often each place has been water, 1984-2021.

    python -m training.flood.water --data-root <path to mmflood/> --out <jrc dir>

A single post-flood radar image shows all open water as dark, so the model cannot otherwise separate
new flood from rivers, lakes and sea. This downloads the 10-degree tiles that cover MMFlood.
"""

from __future__ import annotations

import argparse
import math
import urllib.request
from pathlib import Path

import numpy as np

NO_DATA = 255
PERMANENT = 50
URL = "https://storage.googleapis.com/global-surface-water/downloads2021/occurrence/"
FILE = "occurrence_{}v1_4_2021.tif"


def tile_names(left: float, bottom: float, right: float, top: float) -> list[str]:
    """JRC tiles covering a box. A tile is 10 degrees and named by its north-west corner."""
    names = []
    for lon in range(math.floor(left / 10) * 10, math.ceil(right / 10) * 10, 10):
        for north in range(math.floor(bottom / 10) * 10 + 10, math.ceil(top / 10) * 10 + 1, 10):
            names.append(
                f"{abs(lon)}{'W' if lon < 0 else 'E'}_{abs(north)}{'S' if north < 0 else 'N'}"
            )
    return names


def read_occurrence(jrc_dir: Path, shape, transform, crs, bounds) -> np.ndarray:
    """Occurrence on the target grid: 0 to 100 percent, or NO_DATA where JRC has no observation."""
    import rasterio
    from rasterio.warp import Resampling, reproject

    out = np.full(shape, NO_DATA, dtype=np.uint8)
    for name in tile_names(bounds.left, bounds.bottom, bounds.right, bounds.top):
        part = np.full(shape, NO_DATA, dtype=np.uint8)
        with rasterio.open(jrc_dir / FILE.format(name)) as src:
            reproject(
                rasterio.band(src, 1),
                part,
                src_nodata=NO_DATA,
                dst_transform=transform,
                dst_crs=crs,
                dst_nodata=NO_DATA,
                resampling=Resampling.nearest,
            )
        out = np.where(part != NO_DATA, part, out)
    return out


def water_channel(occurrence: np.ndarray) -> np.ndarray:
    """1 where a place is water at least half the time. No data counts as not known to be water.

    The record runs to 2021, so low percentages can contain the very flood being labelled, which a
    future flood's map would not. A flood lifts the long-run share past one half only rarely.
    """
    return ((occurrence >= PERMANENT) & (occurrence != NO_DATA)).astype(np.float32)


def download(name: str, out: Path) -> int:
    """Fetch one tile unless a complete copy exists. A partial file never takes the final name."""
    target = out / FILE.format(name)
    request = urllib.request.Request(URL + target.name, headers={"User-Agent": "atlas-data"})
    with urllib.request.urlopen(request, timeout=120) as response:
        size = int(response.headers["Content-Length"])
        if target.exists() and target.stat().st_size == size:
            return size
        part = target.with_suffix(".part")
        with open(part, "wb") as handle:
            while chunk := response.read(1 << 20):
                handle.write(chunk)
    if part.stat().st_size != size:
        raise OSError(f"{name}: got {part.stat().st_size} of {size} bytes")
    part.replace(target)
    return size


def main() -> None:
    import rasterio

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    names: set[str] = set()
    for path in sorted((args.data_root / "activations").glob("*/s1_raw/*.tif")):
        with rasterio.open(path) as src:
            names.update(tile_names(*src.bounds))
    total = 0
    for i, name in enumerate(sorted(names), 1):
        total += download(name, args.out)
        print(f"{i}/{len(names)} {name} {total / 1e9:.2f} GB", flush=True)


if __name__ == "__main__":
    main()
