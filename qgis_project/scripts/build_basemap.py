"""Basemap data for the overview map: Copernicus DEM hillshade and country outlines for the locator.

Run with QGIS's Python:
    "C:\\Program Files\\QGIS 4.0.2\\bin\\python-qgis.bat" qgis_project\\scripts\\build_basemap.py

Writes to qgis_project/basemap/:
  copernicus_dem30.tif            Copernicus DEM GLO-30, cut to the overview extent, EPSG:32645, 30 m
  hillshade_multidirectional.tif  multidirectional hillshade of it
  ne_50m_admin_0_countries.zip    Natural Earth 1:50m countries (public domain), for the locator map
DEM: Copernicus WorldDEM-30 (c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space GmbH 2014-2018,
provided under COPERNICUS by the European Union and ESA.
"""
import urllib.request
from pathlib import Path

from osgeo import gdal

gdal.UseExceptions()
OUT = Path(__file__).resolve().parents[1] / "basemap"
BBOX = (248800, 3065900, 364800, 3146600)  # same extent as the Sentinel-2 overview mosaic (EPSG:32645)
TILES = ["N27_00_E084_00", "N27_00_E085_00", "N28_00_E084_00", "N28_00_E085_00"]
DEM_URL = "https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{t}_DEM/Copernicus_DSM_COG_10_{t}_DEM.tif"
NE_URL = "https://naciscdn.org/naturalearth/50m/cultural/ne_50m_admin_0_countries.zip"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    dem = OUT / "copernicus_dem30.tif"
    if not dem.exists():
        print("warping DEM tiles ...", flush=True)
        gdal.Warp(str(dem), ["/vsicurl/" + DEM_URL.format(t=t) for t in TILES], dstSRS="EPSG:32645",
                  outputBounds=BBOX, xRes=30, yRes=30, resampleAlg="bilinear", outputType=gdal.GDT_Float32,
                  creationOptions=["COMPRESS=DEFLATE", "PREDICTOR=3", "TILED=YES"])
    hs = OUT / "hillshade_multidirectional.tif"
    gdal.DEMProcessing(str(hs), str(dem), "hillshade", multiDirectional=True, zFactor=1.5,
                       creationOptions=["COMPRESS=DEFLATE", "TILED=YES"])
    ne = OUT / "ne_50m_admin_0_countries.zip"
    if not ne.exists():
        req = urllib.request.Request(NE_URL, headers={"User-Agent": "Mozilla/5.0"})
        ne.write_bytes(urllib.request.urlopen(req, timeout=120).read())
    for f in sorted(OUT.iterdir()):
        print(f"{f.name}: {f.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
