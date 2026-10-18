# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "rasterio", "pyproj"]
# ///
"""Download 10 m post-event Sentinel-2 true colour for each map-inset frame (panels c-e).

    uv run qgis_project/scripts/download_sentinel2_insets.py
    uv run qgis_project/scripts/download_sentinel2_insets.py --start 2026-10-01 --end 2026-10-18 --maxcc 10

Frames come from analysis/inputs/inset_frames.geojson. Uses the same Sentinel Hub configuration as
download_sentinel2_overview.py. Writes qgis_project/imagery/sentinel2/insets/<panel>_S2_<from>_<to>.tif.
"""
import argparse
import io
import json
import urllib.parse
import urllib.request
from pathlib import Path

import rasterio
from pyproj import Transformer
from rasterio.transform import from_bounds

from download_sentinel2_overview import wms_base_url

ROOT = Path(__file__).resolve().parents[2]
FRAMES = ROOT / "analysis" / "inputs" / "inset_frames.geojson"
OUT = ROOT / "qgis_project" / "imagery" / "sentinel2" / "insets"
RES = 10.0  # metres


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--start", default="2026-08-27")
    ap.add_argument("--end", default="2026-10-18")
    ap.add_argument("--maxcc", type=int, default=30, help="max scene cloud cover, percent")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    to_utm = Transformer.from_crs(4326, 32645, always_xy=True)
    base = wms_base_url()
    for feat in json.loads(FRAMES.read_text(encoding="utf-8"))["features"]:
        ring = feat["geometry"]["coordinates"][0]
        xs, ys = zip(*(to_utm.transform(x, y) for x, y in ring))
        bbox = (round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys)))
        w, h = round((bbox[2] - bbox[0]) / RES), round((bbox[3] - bbox[1]) / RES)
        params = {"SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.3.0", "LAYERS": "1_TRUE_COLOR", "STYLES": "",
                  "FORMAT": "image/png", "TRANSPARENT": "false", "CRS": "EPSG:32645", "BBOX": ",".join(map(str, bbox)),
                  "WIDTH": w, "HEIGHT": h, "TIME": f"{args.start}/{args.end}", "MAXCC": args.maxcc,
                  "PRIORITY": "leastCC", "SHOWLOGO": "false"}
        with urllib.request.urlopen(base + "?" + urllib.parse.urlencode(params), timeout=300) as r:
            data = r.read()
            if not r.headers.get("Content-Type", "").startswith("image/"):
                raise SystemExit(data[:500].decode("utf-8", "replace"))
        with rasterio.MemoryFile(io.BytesIO(data)) as mem, mem.open() as src:
            img = src.read()[:3]
        dst = OUT / f"{feat['properties']['panel']}_S2_{args.start}_{args.end}.tif"
        with rasterio.open(dst, "w", driver="GTiff", dtype="uint8", count=3, width=w, height=h, crs="EPSG:32645",
                           transform=from_bounds(*bbox, w, h), compress="deflate", photometric="RGB") as out:
            out.write(img)
        print(f"wrote {dst.name} ({w}x{h} px)")


if __name__ == "__main__":
    main()
