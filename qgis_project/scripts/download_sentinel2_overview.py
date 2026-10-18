# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "rasterio"]
# ///
"""Download a Sentinel-2 true-colour mosaic for the overview map (panel a) as a local GeoTIFF.

    uv run qgis_project/scripts/download_sentinel2_overview.py --start 2026-10-01 --end 2026-10-18 --maxcc 10

Uses the Copernicus Data Space Sentinel Hub WMS configuration already in overviewmap.qgz (added by
the Sentinel Hub plugin), so no credentials are stored here. Writes
qgis_project/imagery/sentinel2/S2_L1C_truecolor_<from>_<to>.tif in EPSG:32645.
"""
import argparse
import io
import re
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "qgis_project" / "overviewmap.qgz"
OUT = ROOT / "qgis_project" / "imagery" / "sentinel2"

# Overview extent (EPSG:32645) with a few km to spare around the map frame.
BBOX = (248800, 3065900, 364800, 3146600)
MAX_PX = 2500  # Sentinel Hub WMS limit per side
DEFAULT_TIME = ("2026-08-27", "2026-10-15")  # post-event


def wms_base_url():
    with zipfile.ZipFile(PROJECT) as z:
        qgs = z.read(next(n for n in z.namelist() if n.endswith(".qgs"))).decode("utf-8")
    m = re.search(r"url=(https%3A%2F%2Fsh\.dataspace\.copernicus\.eu%2Fogc%2Fwms%2F[0-9a-fA-F-]+)", qgs)
    if not m:
        raise SystemExit("no Sentinel Hub WMS layer found in overviewmap.qgz; add one with the Sentinel Hub plugin")
    return urllib.parse.unquote(m.group(1))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--start", default=DEFAULT_TIME[0])
    ap.add_argument("--end", default=DEFAULT_TIME[1])
    ap.add_argument("--maxcc", type=int, default=30, help="max scene cloud cover, percent")
    args = ap.parse_args()
    TIME = (args.start, args.end)
    OUT.mkdir(parents=True, exist_ok=True)
    w_m, h_m = BBOX[2] - BBOX[0], BBOX[3] - BBOX[1]
    width = MAX_PX if w_m >= h_m else round(MAX_PX * w_m / h_m)
    height = round(width * h_m / w_m)
    params = {"SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.3.0", "LAYERS": "1_TRUE_COLOR", "STYLES": "",
              "FORMAT": "image/png", "TRANSPARENT": "false", "CRS": "EPSG:32645", "BBOX": ",".join(map(str, BBOX)),
              "WIDTH": width, "HEIGHT": height, "TIME": f"{TIME[0]}/{TIME[1]}", "MAXCC": args.maxcc,
              "PRIORITY": "leastCC", "SHOWLOGO": "false"}
    url = wms_base_url() + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=300) as r:
        data = r.read()
        if not r.headers.get("Content-Type", "").startswith("image/"):
            raise SystemExit(data[:500].decode("utf-8", "replace"))
    with rasterio.MemoryFile(io.BytesIO(data)) as mem, mem.open() as src:
        img = src.read()[:3]
    dst = OUT / f"S2_L1C_truecolor_{TIME[0]}_{TIME[1]}.tif"
    profile = {"driver": "GTiff", "dtype": "uint8", "count": 3, "width": width, "height": height, "crs": "EPSG:32645",
               "transform": from_bounds(*BBOX, width, height), "compress": "deflate", "tiled": True, "photometric": "RGB"}
    with rasterio.open(dst, "w", **profile) as out:
        out.write(img)
    print(f"wrote {dst} ({width}x{height} px, {w_m / width:.0f} m/px, mean {img.mean():.0f})")


if __name__ == "__main__":
    main()
