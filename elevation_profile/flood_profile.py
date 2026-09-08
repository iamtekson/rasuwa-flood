"""
Core pipeline for the Bhotekoshi/Trishuli flood elevation profile.

Steps:
1. Merge the (fragmented) river geometry in data/bhotekoshi_river.geojson into a
   single ordered polyline, dropping disconnected braids/spurs.
2. Densify that polyline and sample elevation from data/tiff/dem_2km_buffer.tif
   to build a distance-vs-elevation profile.
3. Load the "flood_profile" cities from data/cities.geojson, snap each one onto
   the river line (nearest point), and read its elevation/position off the
   profile built in step 2 -- a city does not need to sit exactly on the river.
4. Provide helpers to render a static chart and a matplotlib animation that
   mimic the look of _extra/elevation_profile_animation.R.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from shapely.geometry import LineString, Point, shape
from shapely.ops import linemerge, transform as shp_transform

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

RIVER_PATH = DATA_DIR / "bhotekoshi_river.geojson"
DEM_PATH = DATA_DIR / "tiff" / "dem_2km_buffer.tif"
CITIES_PATH = DATA_DIR / "cities.geojson"

# Metric CRS used only for distance/interpolation math (UTM 45N covers this basin).
METRIC_CRS = "EPSG:32645"
WGS84 = "EPSG:4326"

_TO_METRIC = Transformer.from_crs(WGS84, METRIC_CRS, always_xy=True).transform
_TO_WGS84 = Transformer.from_crs(METRIC_CRS, WGS84, always_xy=True).transform


# ---------------------------------------------------------------------------
# 1. River line reconstruction
# ---------------------------------------------------------------------------

def _dist(a, b) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def merge_river_line(path: Path = RIVER_PATH, max_gap_m: float = 5000.0) -> LineString:
    """Stitch every LineString/MultiLineString part in the river geojson into one
    ordered polyline (upstream -> downstream not guaranteed, just connected),
    greedily attaching the nearest remaining part to either end of the growing
    chain. Parts that never come within `max_gap_m` of an end (river braids,
    duplicate side-channels) are dropped rather than force-joined.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_lines = []
    for feat in data["features"]:
        geom = shape(feat["geometry"])
        if geom.geom_type == "LineString":
            raw_lines.append(geom)
        elif geom.geom_type == "MultiLineString":
            raw_lines.extend(geom.geoms)

    merged = linemerge(raw_lines)
    parts = [list(g.coords) for g in getattr(merged, "geoms", [merged])]

    threshold_deg = max_gap_m / 111_320.0
    seed = max(range(len(parts)), key=lambda i: len(parts[i]))
    chain = list(parts[seed])
    remaining = set(range(len(parts))) - {seed}

    while remaining:
        head, tail = chain[0], chain[-1]
        best = None  # (gap, idx, end, forward)
        for i in remaining:
            p = parts[i]
            for gap, end, fwd in (
                (_dist(tail, p[0]), "tail", True),
                (_dist(tail, p[-1]), "tail", False),
                (_dist(head, p[0]), "head", False),
                (_dist(head, p[-1]), "head", True),
            ):
                if best is None or gap < best[0]:
                    best = (gap, i, end, fwd)
        gap, i, end, fwd = best
        if gap > threshold_deg:
            break
        p = parts[i] if fwd else parts[i][::-1]
        if end == "tail":
            chain.extend(p[1:] if _dist(chain[-1], p[0]) < 1e-9 else p)
        else:
            chain = (p[:-1] if _dist(p[-1], chain[0]) < 1e-9 else p) + chain
        remaining.discard(i)

    line = LineString(chain)
    # Orient north -> south (upstream -> downstream) for readability.
    if line.coords[0][1] < line.coords[-1][1]:
        line = LineString(list(line.coords)[::-1])
    return line


# ---------------------------------------------------------------------------
# 2. Elevation profile along the line
# ---------------------------------------------------------------------------

def build_profile(line_wgs84: LineString, dem_path: Path = DEM_PATH, step_m: float = 50.0) -> pd.DataFrame:
    """Densify `line_wgs84` every `step_m` metres and sample DEM elevation at
    each point. Returns a DataFrame with lon, lat, distance_km, elevation_m.
    """
    line_m = shp_transform(_TO_METRIC, line_wgs84)
    total_len = line_m.length
    n_steps = max(int(total_len // step_m), 1)
    distances_m = np.linspace(0, total_len, n_steps + 1)
    pts_m = [line_m.interpolate(d) for d in distances_m]
    pts_wgs = [shp_transform(_TO_WGS84, p) for p in pts_m]

    lons = np.array([p.x for p in pts_wgs])
    lats = np.array([p.y for p in pts_wgs])

    with rasterio.open(dem_path) as ds:
        nodata = ds.nodata
        elevations = np.array([v[0] for v in ds.sample(zip(lons, lats))], dtype="float64")
    if nodata is not None:
        elevations[elevations == nodata] = np.nan
    # DEM has small pixel-level noise/pits; a short rolling median smooths the
    # profile without hiding the overall drop, similar to a real elevation trace.
    elevations = (
        pd.Series(elevations).interpolate(limit_direction="both").rolling(5, center=True, min_periods=1).median().to_numpy()
    )

    return pd.DataFrame(
        {
            "lon": lons,
            "lat": lats,
            "distance_km": distances_m / 1000.0,
            "elevation_m": elevations,
        }
    )


# ---------------------------------------------------------------------------
# 3. Cities: load + snap onto the river/profile
# ---------------------------------------------------------------------------

def load_flood_cities(path: Path = CITIES_PATH) -> pd.DataFrame:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for feat in data["features"]:
        props = feat["properties"]
        if not props.get("flood_profile"):
            continue
        lon, lat = feat["geometry"]["coordinates"]
        rows.append(
            {
                "name": props.get("name_en") or props.get("name"),
                "name_local": props.get("name"),
                "lon": lon,
                "lat": lat,
                "flood_order": props.get("flood_order", 9999),
                "flood_time": props.get("flood_time"),
                "flood_reached": bool(props.get("flood_reached", True)),
            }
        )
    df = pd.DataFrame(rows).sort_values("flood_order").reset_index(drop=True)
    return df


def snap_cities_to_profile(cities: pd.DataFrame, line_wgs84: LineString, profile: pd.DataFrame) -> pd.DataFrame:
    """For each city, project it onto the river line to get distance-along-line,
    then read elevation off the *profile* at that distance (never the city's
    own DEM value) -- so a city a couple of km from the mapped river still
    gets a sensible position and elevation.
    """
    line_m = shp_transform(_TO_METRIC, line_wgs84)
    out = cities.copy()
    snap_dist_km = []
    snap_lon = []
    snap_lat = []
    offset_m = []
    for _, row in cities.iterrows():
        pt_m = shp_transform(_TO_METRIC, Point(row["lon"], row["lat"]))
        along_m = line_m.project(pt_m)
        snapped_m = line_m.interpolate(along_m)
        snapped_wgs = shp_transform(_TO_WGS84, snapped_m)
        snap_dist_km.append(along_m / 1000.0)
        snap_lon.append(snapped_wgs.x)
        snap_lat.append(snapped_wgs.y)
        offset_m.append(pt_m.distance(snapped_m))

    out["distance_km"] = snap_dist_km
    out["snap_lon"] = snap_lon
    out["snap_lat"] = snap_lat
    out["offset_from_river_m"] = offset_m
    out["elevation_m"] = np.interp(out["distance_km"], profile["distance_km"], profile["elevation_m"])
    return out.sort_values("distance_km").reset_index(drop=True)


# ---------------------------------------------------------------------------
# 4. Stopwatch helper (mirrors the R script's approx() based clock)
# ---------------------------------------------------------------------------

@dataclass
class Stopwatch:
    control_km: np.ndarray
    control_sec: np.ndarray

    @classmethod
    def from_annotations(cls, annotations: pd.DataFrame, start_km: float, start_time: str) -> "Stopwatch":
        def hms_to_sec(s: str) -> float:
            h, m, sec = (int(x) for x in s.split(":"))
            return h * 3600 + m * 60 + sec

        known = annotations.dropna(subset=["flood_time"])
        km = [start_km] + known["distance_km"].tolist()
        sec = [hms_to_sec(start_time)] + [hms_to_sec(t) for t in known["flood_time"]]
        order = np.argsort(km)
        return cls(np.array(km)[order], np.array(sec)[order])

    def time_at(self, distance_km: float) -> float:
        if distance_km >= self.control_km[-1]:
            return self.control_sec[-1]
        return float(np.interp(distance_km, self.control_km, self.control_sec))

    @staticmethod
    def sec_to_hms(sec: float) -> str:
        sec = int(round(sec))
        return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"
