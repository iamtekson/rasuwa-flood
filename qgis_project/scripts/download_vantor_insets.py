"""Clip Vantor open-data imagery to the map-inset frames (panels c-e), at native resolution.

Run with QGIS's Python (it has GDAL with HTTP support):
    "C:\\Program Files\\QGIS 4.0.2\\bin\\python-qgis.bat" qgis_project\\scripts\\download_vantor_insets.py

Reads the frames from analysis/inputs/inset_frames.geojson and writes cloud-optimised GeoTIFFs
to qgis_project/imagery/vantor/, plus vantor_footprints.geojson listing every scene in the event
collection (with its URL, so any scene can also be streamed straight into QGIS).
Imagery: Vantor Open Data, Nepal-Flooding-Aug-2026, licence CC BY-NC 4.0.
"""
import json
import urllib.request
from pathlib import Path

from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "qgis_project" / "imagery" / "vantor"
FRAMES = ROOT / "analysis" / "inputs" / "inset_frames.geojson"
COLLECTION = "https://vantor-opendata.s3.amazonaws.com/events/Nepal-Flooding-Aug-2026/collection.json"

# (panel, phase, scene id): clearest post-event and most recent useful pre-event scene per frame,
# picked from low-resolution previews of every scene that covers the frame. Panel d has no
# post-event Vantor coverage.
SCENES = [
    ("c", "post", "B040001100881610"),  # 2026-08-27 WV03 0.31 m, off-nadir 9 deg
    ("c", "pre", "10500100364E8400"),   # 2023-09-17 GE01 0.43 m (covers ~75% of the frame)
    ("d", "pre", "10300100FCB83600"),   # 2024-05-29 WV02 0.58 m (covers ~80% of the frame)
    ("e", "post", ("B030001100EF5210", "B030001100EF5510")),  # 2026-09-08 WV02 0.48 m, two tiles of one pass
    ("e", "pre", "B160001100CDB210"),   # 2026-02-05 LG06 0.35 m, cloud-free
]


def load_json(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def frame_bounds():
    ds = ogr.Open(str(FRAMES))
    lyr = ds.GetLayer()
    out = {}
    for f in lyr:
        g = f.GetGeometryRef()
        out[f.GetField("panel")] = (g.Clone(), lyr.GetSpatialRef().Clone())
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    gdal.SetConfigOption("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")
    collection = load_json(COLLECTION)
    items = {}
    for link in collection["links"]:
        if link["rel"] == "item":
            it = load_json(link["href"])
            items[it["id"]] = it

    # catalogue of every scene, for browsing in QGIS
    feats = []
    for it in items.values():
        p = it["properties"]
        feats.append({"type": "Feature", "geometry": it["geometry"], "properties": {
            "id": it["id"], "phase": p.get("phase"), "date": p["datetime"][:10], "satellite": p.get("vehicle_name"),
            "gsd_m": p.get("pan_gsd"), "cloud_pct": p.get("eo:cloud_cover"), "off_nadir": p.get("view:off_nadir"),
            "cog_url": it["assets"]["visual"]["href"], "vsicurl": "/vsicurl/" + it["assets"]["visual"]["href"]}})
    (OUT / "vantor_footprints.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")

    frames = frame_bounds()
    for panel, phase, sids in SCENES:
        sids = (sids,) if isinstance(sids, str) else sids  # several tiles of one pass: later ones on top
        it = items[sids[-1]]
        urls = ["/vsicurl/" + items[s]["assets"]["visual"]["href"] for s in sids]
        date = it["properties"]["datetime"][:10]
        dst = OUT / f"{panel}_{phase}_{date}_{it['properties'].get('vehicle_name')}_{'+'.join(sids)}.tif"
        if dst.exists():
            print("exists:", dst.name)
            continue
        src = gdal.Open(urls[-1])
        geom, srs = frames[panel]
        geom = geom.Clone()
        tgt = osr.SpatialReference(wkt=src.GetProjection())
        for s in (srs, tgt):
            s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        geom.Transform(osr.CoordinateTransformation(srs, tgt))
        minx, maxx, miny, maxy = geom.GetEnvelope()
        print(f"clipping {'+'.join(sids)} ({date}, {phase}) to frame {panel} ...", flush=True)
        opts = ["COMPRESS=JPEG", "QUALITY=90", "BIGTIFF=IF_SAFER", "NUM_THREADS=ALL_CPUS"]
        if len(urls) == 1:
            gdal.Translate(str(dst), src, projWin=[minx, maxy, maxx, miny], format="COG", creationOptions=opts)
        else:
            gt = src.GetGeoTransform()
            gdal.Warp(str(dst), urls, outputBounds=[minx, miny, maxx, maxy], xRes=gt[1], yRes=abs(gt[5]),
                      srcNodata=0, dstNodata=0, format="COG", creationOptions=opts)
        print(f"  wrote {dst.name} ({dst.stat().st_size / 1e6:.0f} MB)", flush=True)


if __name__ == "__main__":
    main()
