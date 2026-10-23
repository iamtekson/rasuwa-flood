# /// script
# requires-python = ">=3.10"
# dependencies = ["geopandas>=1.0", "pyogrio", "shapely>=2.0", "pyproj", "numpy", "pandas", "rasterio"]
# ///
"""Derive every layer and table the damage figure needs; run this before damage_profile.py.

    uv run analysis/scripts/build_intermediate.py
    uv run analysis/scripts/build_intermediate.py --near-m 50   # width of the "near the inundation" road band
    uv run analysis/scripts/build_intermediate.py --dedupe-m 3  # drop likely duplicate IIT buildings

Writes to analysis/intermediate/ (GeoJSON in EPSG:4326, shapefile in EPSG:32645):
  flow_path/flow_path.geojson            the flow path line
  flow_path/flow_path_km_ticks.*         a point every 1 km, attribute `km`
  elevation_profile.csv                  km, elevation sampled from the DEM every 50 m
  towns.csv                              towns near the flow path with km and flood arrival time (Nepal Time)
  buildings.csv                          IIT building points with km
  roads_in_inundation.geojson            road inside the flood inundation
  roads_near_inundation.geojson          road outside it but within --near-m
  road_pieces.csv                        both, split into ~20 m pieces with km (for binning)
  bridges.geojson                        harmonised bridges (IIT + HOT-only) with status and km
  hydropower.geojson                     hydropower structures with km and short label
  inset_bands.csv                        km range of each map inset (from inputs/inset_frames.geojson)
  impact_by_km.csv                       per-bin totals
  build_info.json                        settings and totals of this build
If inputs/inset_frames.geojson is missing, default frames are written there first.
"""
import argparse
import json

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shapely
from shapely.geometry import box
from shapely.ops import substring

import common as c

# Default map-inset frames, by km along the flow path. They are written once to
# inputs/inset_frames.geojson; edit the polygons there (e.g. in QGIS) and rebuild.
INSET_DEFAULTS = [("c", "Rasuwagadhi-Timure", 19.0, 26.0),
                  ("d", "Upper Trishuli hydropower", 51.5, 63.4),
                  ("e", "Trishuli-Bidur", 67.0, 79.0)]  # km 67-79 lies wholly inside the clear 8 Sep 2026 Vantor pass
FRAME_ASPECT = 1.0   # width / height of the default frames, so panels c-e sit in one row of equal height
CORRIDOR_KM, CORRIDOR_BUFFER_KM = 165, 5  # panel (a) shows the flow path to km 165 (as panel b), +-5 km
LABEL_CLEAR_KM = 2.2         # district and country names at least this far from the river
DISTRICT_LABEL_MIN_KM2 = 100 # districts with less corridor area than this get no name
DISTRICT_LABEL_FROM_KM = 30  # district names only downstream of here, clear of the CHINA / NEPAL names
TOWN_MAX_OFFSET_M = 1500  # towns farther than this from the flow path are left out


def frame_box(segment, pad_m=300, aspect=FRAME_ASPECT):
    """Box around a stretch of the flow path, widened (or heightened) about its centre to `aspect`."""
    x0, y0, x1, y1 = segment.buffer(pad_m).bounds
    cx, cy, w, h = (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0
    w, h = (aspect * h, h) if w / h < aspect else (w, w / aspect)
    return box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def to_wgs(gdf):
    return gdf.to_crs(4326)


def write_flow_path(path, out):
    out.mkdir(parents=True, exist_ok=True)
    line = gpd.GeoDataFrame({"length_km": [round(path.length_km, 3)]}, geometry=[path.line], crs=c.UTM)
    to_wgs(line).to_file(out / "flow_path.geojson")
    km = np.arange(0, int(path.length_km) + 1)
    ticks = gpd.GeoDataFrame({"km": km}, geometry=path.point_at(km), crs=c.UTM)
    to_wgs(ticks).to_file(out / "flow_path_km_ticks.geojson")
    ticks.to_file(out / "flow_path_km_ticks.shp")


def elevation_profile(path, step_m=50.0):
    """Sample the DEM every step_m along the line; a short rolling median removes pixel noise."""
    d = np.arange(0, path.line.length, step_m)
    pts = gpd.GeoSeries(shapely.line_interpolate_point(path.line, d), crs=c.UTM)
    with rasterio.open(c.PATHS["dem"]) as dem:
        xy = pts.to_crs(dem.crs)
        z = np.array([v[0] for v in dem.sample(zip(xy.x, xy.y))], dtype=float)
        if dem.nodata is not None:
            z[z == dem.nodata] = np.nan
    z = pd.Series(z).interpolate(limit_direction="both").rolling(5, center=True, min_periods=1).median()
    ll = pts.to_crs(4326)
    return pd.DataFrame({"km": d / 1000, "elevation_m": z.round(1), "lon": ll.x.round(6), "lat": ll.y.round(6)})


def towns(path):
    t = c.read("cities")
    t["name"] = t.name_en.fillna(t["name"]).str.replace(r"\s*\(.*\)$", "", regex=True)
    t["km"] = path.km_of(t.geometry)
    t["offset_m"] = path.offset_m(t.geometry)
    t["arrival_npt"] = [v.strftime("%H:%M") if hasattr(v, "strftime") else (str(v)[:5] if isinstance(v, str) else None)
                        for v in t.flood_time]
    extra = c.INPUTS / "arrival_times.csv"  # arrival times not in cities.geojson (Nepal Time); these win
    if extra.exists():
        times = pd.read_csv(extra, dtype=str).set_index("name").arrival_npt
        t["arrival_npt"] = t.name.map(times).fillna(t.arrival_npt)
    ll = t.to_crs(4326)
    t["lon"], t["lat"] = ll.geometry.x.round(5), ll.geometry.y.round(5)
    t = t[t.offset_m <= TOWN_MAX_OFFSET_M]
    return t[["name", "km", "offset_m", "arrival_npt", "lon", "lat"]].round({"km": 2, "offset_m": 0}).sort_values("km")


def map_a_layers(path, out):
    """Panel (a) is clipped to a corridor around the flow path. Writes the corridor, district boundaries
    clipped to it, and label points for district and country names, placed inside the corridor but at
    least LABEL_CLEAR_KM from the river so they sit on the hillshade, not on the damage symbols."""
    out.mkdir(parents=True, exist_ok=True)
    seg = substring(path.line, 0, CORRIDOR_KM * 1000)
    corridor = seg.buffer(CORRIDOR_BUFFER_KM * 1000)
    gpd.GeoDataFrame({"km_to": [CORRIDOR_KM], "buffer_km": [CORRIDOR_BUFFER_KM]}, geometry=[corridor],
                     crs=c.UTM).to_crs(4326).to_file(out / "corridor.geojson")
    districts = c.read("districts")
    lines = shapely.union_all(districts.boundary.values).intersection(corridor)
    gpd.GeoDataFrame(geometry=[lines], crs=c.UTM).to_crs(4326).to_file(out / "district_boundaries.geojson")

    def label_point(region):
        region = region.difference(seg.buffer(LABEL_CLEAR_KM * 1000))
        parts = getattr(region, "geoms", [region])
        biggest = max(parts, key=lambda g: g.area) if parts else None
        if biggest is None or biggest.is_empty:
            return None
        return shapely.get_point(shapely.maximum_inscribed_circle(biggest), 0)  # the most open spot

    nepal = shapely.union_all(districts.geometry.values)
    rows = []
    downstream = substring(path.line, DISTRICT_LABEL_FROM_KM * 1000, CORRIDOR_KM * 1000).buffer(CORRIDOR_BUFFER_KM * 1000)
    frames = shapely.union_all(c.read("inset_frames").geometry.values).buffer(1500)  # names stay off the frames
    for d in districts.itertuples():
        part = d.geometry.intersection(downstream).difference(frames)  # clear of the border reach and frames
        if part.area / 1e6 >= DISTRICT_LABEL_MIN_KM2:
            pt = label_point(part)
            if pt is not None:
                rows.append({"text": d.DISTRICT.upper(), "kind": "district", "geometry": pt})
    for text, (k0, k1), inside in [("CHINA", (3, 12), False), ("NEPAL", (21, 32), True)]:
        reach = substring(path.line, k0 * 1000, k1 * 1000).buffer(CORRIDOR_BUFFER_KM * 1000)
        pt = label_point(reach.intersection(nepal) if inside else reach.difference(nepal))
        if pt is not None:
            rows.append({"text": text, "kind": "country", "geometry": pt})
    gpd.GeoDataFrame(rows, crs=c.UTM).to_crs(4326).to_file(out / "label_points.geojson")
    return corridor


def inset_bands(path):
    frames_path = c.PATHS["inset_frames"]
    if not frames_path.exists():
        frames = [frame_box(substring(path.line, a * 1000, b * 1000)) for _, _, a, b in INSET_DEFAULTS]
        gpd.GeoDataFrame({"panel": [p for p, *_ in INSET_DEFAULTS], "place": [n for _, n, *_ in INSET_DEFAULTS]},
                         geometry=frames, crs=c.UTM).to_crs(4326).to_file(frames_path)
        print(f"wrote default inset frames to {frames_path}")
    frames = c.read("inset_frames")
    rows = []
    for f in frames.itertuples():
        inside = path.line.intersection(f.geometry)
        ends = [pt for part in getattr(inside, "geoms", [inside]) for pt in (part.coords[0], part.coords[-1])]
        km = [path.line.project(shapely.Point(pt)) / 1000 for pt in ends]
        rows.append({"panel": f.panel, "place": f.place, "km_from": round(min(km), 2), "km_to": round(max(km), 2)})
    return pd.DataFrame(rows).sort_values("km_from")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--near-m", type=float, default=100, help="width of the road band just outside the inundation (default 100 m)")
    ap.add_argument("--dedupe-m", type=float, default=0.0, help="drop no-ID IIT buildings within this many m of an ID'd one")
    ap.add_argument("--bin", type=float, default=5, help="bin width (km) for impact_by_km.csv")
    args = ap.parse_args()
    out = c.INTERMEDIATE
    out.mkdir(parents=True, exist_ok=True)
    path = c.FlowPath()

    write_flow_path(path, out / "flow_path")
    elevation_profile(path).to_csv(out / "elevation_profile.csv", index=False)
    towns(path).to_csv(out / "towns.csv", index=False)
    bands = inset_bands(path)  # first: it writes the default inset frames if there are none yet
    map_a_layers(path, out / "map_a")
    bands.to_csv(out / "inset_bands.csv", index=False)

    bld = c.iit_buildings(args.dedupe_m)
    bld_tab = pd.DataFrame({"id": bld.id.values, "km": path.km_of(bld.geometry).round(3)})
    bld_tab.to_csv(out / "buildings.csv", index=False)

    # roads: the whole network clipped to the inundation, and to a band of --near-m just outside it
    flood = c.inundation()
    near = flood.buffer(args.near_m).difference(flood)
    net = c.road_network()
    net = net[net.intersects(flood.buffer(args.near_m))]
    pieces = []
    for zone, poly, name in [("in", flood, "roads_in_inundation"), ("near", near, "roads_near_inundation")]:
        r = net.assign(geometry=net.intersection(poly))
        r = r[~r.geometry.is_empty & (r.length > 0)].copy()
        r["length_m"] = r.length.round(1)
        r["km"] = path.km_of(r.geometry).round(3)
        to_wgs(r).to_file(out / f"{name}.geojson")
        pieces.append(path.sample_lines(r, columns=("road_class",)).assign(zone=zone))
    roads = pd.concat(pieces, ignore_index=True)
    roads.round({"km": 3, "length_m": 2}).to_csv(out / "road_pieces.csv", index=False)

    _, _, bridges = c.harmonised_bridges(path)
    to_wgs(bridges.round({"km": 3})).to_file(out / "bridges.geojson")
    hp = c.hydropower(path)
    to_wgs(hp.round({"km": 3})).to_file(out / "hydropower.geojson")

    edges = np.arange(0, np.ceil(path.length_km / args.bin) * args.bin + args.bin, args.bin)
    def hist(km, weights=None):
        return np.histogram(km, bins=edges, weights=weights)[0]

    def road_km(zone, cls=None):
        sel = roads.zone == zone
        if cls:
            sel &= roads.road_class == cls
        return hist(roads.km[sel], roads.length_m[sel]) / 1000

    table = pd.DataFrame({
        "km_from": edges[:-1], "km_to": edges[1:],
        "buildings": hist(bld_tab.km),
        "road_km_main": road_km("in", "main").round(2),
        "road_km_local": road_km("in", "local").round(2),
        f"road_km_within_{args.near_m:g}m": road_km("near").round(2),
        **{f"bridges_{s.lower().replace(' ', '_')}": hist(bridges.km[bridges.status == s])
           for s in ("Destroyed", "Damaged", "Intact", "No info")},
        "hydropower_structures": hist(hp.km),
    })
    table.to_csv(out / "impact_by_km.csv", index=False)

    in_roads = roads[roads.zone == "in"]
    info = {
        "flow_path": c.PATHS["flow_path"].relative_to(c.ROOT).as_posix(),
        "flow_path_length_km": round(path.length_km, 3),
        "inundation": c.PATHS["inundation"].relative_to(c.ROOT).as_posix(),
        "inundation_km2": round(flood.area / 1e6, 2),
        "near_m": args.near_m,
        "dedupe_m": args.dedupe_m,
        "buildings": int(len(bld_tab)),
        "road_km_in_inundation": round(in_roads.length_m.sum() / 1000, 1),
        "road_km_in_inundation_main": round(in_roads.length_m[in_roads.road_class == "main"].sum() / 1000, 1),
        "road_km_near_inundation": round(roads.length_m[roads.zone == "near"].sum() / 1000, 1),
        "bridges": bridges.status.value_counts().to_dict(),
        "hydropower_structures": int(len(hp)),
        "inset_bands": bands.to_dict("records"),
    }
    (out / "build_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
