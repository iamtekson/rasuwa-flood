# /// script
# requires-python = ">=3.10"
# dependencies = ["geopandas>=1.0", "pyogrio", "shapely>=2.0", "pyproj", "numpy", "pandas"]
# ///
"""Helper layers for the QGIS map panels, plus the per-bin damage table behind the profile.

    uv run analysis/build_layers.py

Writes to analysis/output/ (all GeoJSON in EPSG:4326):
  flowpath.geojson                  flow line, km 0 (source) to --xmax
  flowpath_km_ticks.geojson         a point every 10 km, attribute `km` (label it on the map)
  bridges_harmonised.geojson        IIT bridges: normalised status, matched HOT bridge, agreement flag
  bridges_hot_only.geojson          HOT bridges with no IIT bridge within 100 m
  hydropower.geojson                hydropower structures incl. Upper Trishuli-2, with km
  impact_by_km.csv                  per-bin buildings, roads (damaged / within 100 m), bridges, flooded width
"""
import argparse

import geopandas as gpd
import numpy as np
import pandas as pd

import common as c


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bin", type=float, default=5)
    ap.add_argument("--xmax", type=float, default=170)
    args = ap.parse_args()
    c.OUT.mkdir(parents=True, exist_ok=True)
    path = c.FlowPath()
    edges = np.arange(0, args.xmax + args.bin, args.bin)

    gpd.GeoDataFrame({"name": ["flow path (portal elevation profile)"]}, geometry=[path.line_until(args.xmax)],
                     crs=c.UTM).to_crs(4326).to_file(c.OUT / "flowpath.geojson")
    ticks = np.arange(0, args.xmax + 1, 10)
    gpd.GeoDataFrame({"km": ticks}, geometry=path.point_at(ticks), crs=c.UTM).to_crs(4326).to_file(c.OUT / "flowpath_km_ticks.geojson")

    iit, hot_only, union = c.harmonised_bridges(path)
    iit.rename(columns={"begin": "type", "timestamp": "place"})[
        ["id", "descriptio", "status_iit", "status_hot", "status", "agreement", "type", "place", "hot_name", "hot_dist_m", "km", "geometry"]
    ].to_crs(4326).to_file(c.OUT / "bridges_harmonised.geojson")
    hot_only[["name", "status", "location", "km", "geometry"]].to_crs(4326).to_file(c.OUT / "bridges_hot_only.geojson")
    hp = c.hydropower(path)
    hp.to_crs(4326).to_file(c.OUT / "hydropower.geojson")

    bld = c.read("iit_buildings")
    dmg = c.read("roads_damaged")
    width = path.area_by_bin(c.dissolve(c.read("iit_inundation")), edges) / (args.bin * 1000)
    hist = lambda km, sel=None: np.histogram(km if sel is None else km[sel], bins=edges)[0]
    table = pd.DataFrame({
        "km_from": edges[:-1], "km_to": edges[1:],
        "flooded_width_m_iit": width.round(0),
        "buildings_iit": hist(path.km_of(bld.geometry)),
        "road_km_main": path.line_length_by_bin(dmg[dmg.highway.isin(c.MAIN_ROADS)], edges).round(2),
        "road_km_local": path.line_length_by_bin(dmg[~dmg.highway.isin(c.MAIN_ROADS)], edges).round(2),
        "road_km_within_100m": path.line_length_by_bin(c.read("roads_endangered"), edges).round(2),
        "bridges_destroyed": hist(union.km.values, (union.status == "Destroyed").values),
        "bridges_damaged": hist(union.km.values, (union.status == "Damaged").values),
        "bridges_intact": hist(union.km.values, (union.status == "Intact").values),
        "bridges_no_info": hist(union.km.values, (union.status == "No info").values),
        "hydropower_structures": hist(hp.km.values),
    })
    table.to_csv(c.OUT / "impact_by_km.csv", index=False)
    print(table.sum(numeric_only=True).drop(["km_from", "km_to", "flooded_width_m_iit"]).round(1).to_string())
    print("bridge agreement:", iit.agreement.value_counts().to_dict(), "| HOT-only:", len(hot_only))
    print(f"wrote layers and impact_by_km.csv to {c.OUT}")


if __name__ == "__main__":
    main()
