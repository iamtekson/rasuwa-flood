# /// script
# requires-python = ">=3.10"
# dependencies = ["geopandas>=1.0", "pyogrio", "shapely>=2.0", "pyproj", "numpy", "pandas", "rasterio"]
# ///
"""Package the flow-path line behind "distance from source" for collaborators.

    uv run analysis/export_flowpath.py

Writes analysis/output/rasuwa_flow_path.zip with the full-resolution river line the portal's
elevation profile was measured on, 1 km tick points, both as GeoJSON and shapefile, and a README.
Measuring along this line in EPSG:32645 reproduces the km used in the damage profile.
"""
import shutil
import sys
import zipfile

import geopandas as gpd
import numpy as np
from shapely.geometry import Point
from shapely.ops import substring

import common as c

sys.path.insert(0, str(c.ROOT / "elevation_profile"))
from flood_profile import merge_river_line  # noqa: E402  (same line the elevation profile was built on)

LANDMARKS = {"Devighat": (85.1088, 27.8605), "Mugling (approx.)": (84.5556, 27.8556)}


def main():
    # The profile is the first `profile_km` of the merged river line (the rest runs on past Chanauli).
    full = gpd.GeoSeries([merge_river_line()], crs=4326).to_crs(c.UTM).iloc[0]
    profile = c.FlowPath().profile
    profile_km = profile["distance_km"][-1]
    line = substring(full, 0, profile_km * 1000)
    length_km = line.length / 1000
    start = gpd.GeoSeries([Point(profile["lon"][0], profile["lat"][0])], crs=4326).to_crs(c.UTM).iloc[0]
    assert Point(line.coords[0]).distance(start) < 50, "merged line does not start at the profile's source"

    km = np.arange(0, int(length_km) + 1)
    ticks = gpd.GeoDataFrame({"km": km}, geometry=[line.interpolate(k * 1000) for k in km], crs=c.UTM)
    places = {t["name"]: (t["lon"], t["lat"]) for t in c.FlowPath().profile["cities"]}
    places.update(LANDMARKS)
    landmarks = sorted((line.project(gpd.GeoSeries([Point(xy)], crs=4326).to_crs(c.UTM).iloc[0]) / 1000, name)
                       for name, xy in places.items())

    folder = c.OUT / "rasuwa_flow_path"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    line_gdf = gpd.GeoDataFrame({"name": ["Bhotekoshi-Trishuli flow path"], "length_km": [round(length_km, 3)]},
                                geometry=[line], crs=c.UTM)
    for gdf, stem in [(line_gdf, "flow_path"), (ticks, "flow_path_km_ticks")]:
        gdf.to_crs(4326).to_file(folder / f"{stem}.geojson")
        gdf.to_file(folder / f"{stem}.shp")  # shapefile kept in UTM 45N so GIS length = km directly

    src = line_gdf.to_crs(4326).geometry.iloc[0].coords[0]
    rows = "\n".join(f"  {k:6.1f} km  {name}" for k, name in landmarks if k <= length_km)
    (folder / "README.txt").write_text(f"""Rasuwa flood: flow path used for "distance from source"

flow_path.geojson / .shp           River centreline, source to Chanauli, {length_km:.1f} km, one line.
flow_path_km_ticks.geojson / .shp  A point every 1 km along it; attribute `km`.

km 0 is the flood source at {src[0]:.4f} E, {src[1]:.4f} N. Distances are lengths along this line
in WGS 84 / UTM 45N (EPSG:32645). The shapefiles are already in EPSG:32645, so measuring along the
line in GIS gives the same km; the GeoJSON files are in EPSG:4326. To place a feature, take the
km of its nearest point on the line (e.g. QGIS "Locate points along lines" or ArcGIS "Locate
Features Along Routes"), or use the nearest tick point.

Reference points:
{rows}

The damage-profile figure covers km 0-170.
""", encoding="utf-8")

    zip_path = c.OUT / "rasuwa_flow_path.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(folder.iterdir()):
            z.write(f, f"rasuwa_flow_path/{f.name}")
    print(f"line {length_km:.3f} km (profile {profile_km:.3f} km) | {len(ticks)} ticks")
    print(rows)
    print(f"wrote {zip_path}")


if __name__ == "__main__":
    main()
