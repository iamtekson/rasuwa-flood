"""Shared paths, loaders and the flow-path linear reference for the Rasuwa damage analysis.

Every distance in this analysis is "km from source along the flow path", taken from the
portal's elevation profile (data/elevation_profile.json, km 0 = source lake), so all layers
share one linear reference.
"""
import json
import re
import urllib.request
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

warnings.filterwarnings("ignore", category=RuntimeWarning)

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
DATA = ROOT / "data"
IIT = DATA / "Impact-Assessment-Shashi-Ashim"
OSM = DATA / "OSM"
OUT = HERE / "output"
UTM = 32645  # WGS 84 / UTM zone 45N

# HOT bridge damage is live on S3 and keeps changing; the figure uses a frozen snapshot.
HOT_BRIDGES_URL = "https://production-raw-data-api.s3.amazonaws.com/ISO3/NPL/combined/hot_flood_npl_bridge_damage.geojson"
HOT_BRIDGES = HERE / "data" / "hot_bridge_damage_2026-10-14.geojson"

PATHS = {
    "iit_inundation": IIT / "Inundation" / "Inundation.shp",
    "iit_buildings": IIT / "Builidngs" / "Buildings.shp",
    "iit_roads": IIT / "Impacted_Road" / "Damage_Road.shp",
    "iit_bridges": IIT / "Bridges" / "Bridges.shp",
    "portal_extent": DATA / "flood_extent_v2.geojson",
    "hot_extent": DATA / "hot_flood_npl_flood_extent.geojson",
    "osm_extent": OSM / "1. Area_of_interest_flooded_area" / "flood_extent_Extended_31th_August.geojson",
    "roads_damaged": OSM / "4. Road Network" / "Road_damaged.geojson",
    "roads_endangered": OSM / "4. Road Network" / "Road_endangered.geojson",
    "settlements": OSM / "19. Settlements" / "final_settelement_with_updated_v2.geojson",
    "hydropower": OSM / "13. Hydropower" / "Hydropower_ar_29Aug.geojson",
    "portal_buildings": DATA / "buildings_essential.geojson",
    "hot_bridges": HOT_BRIDGES,
    "profile": DATA / "elevation_profile.json",
}

# OSM highway tags counted as "highways & main roads"; everything else is "local roads & tracks".
MAIN_ROADS = {"motorway", "trunk", "primary", "secondary", "tertiary"}

# The IIT bridge status field has 15 spellings; map them to four classes.
IIT_STATUS = {
    "Washed/Destroyed": "Destroyed", "washed/Destroyed": "Destroyed",
    "Suspension_Destroyed": "Destroyed", "Concreate_Destroyed": "Destroyed",
    "Damaged": "Damaged", "Damage": "Damaged", "damage": "Damaged", "Concreate_Damaged": "Damaged",
    "Affected/Intact": "Intact", "Intact": "Intact", "Not affected/Intact": "Intact",
    "No Info": "No info", "No info": "No info", "No Info Cloud": "No info",
    "Suspension": "No info",  # bridge type typed into the status field
}
HOT_STATUS = {"Washed out": "Destroyed", "Damaged": "Damaged", "Intact": "Intact"}

# Upper Trishuli-2 is in the IIT report (Fig. 4) but not in the OSM working-group layer.
UPPER_TRISHULI_2 = (85.2964, 28.1258)

# Words dropped from hydropower names for figure labels, e.g.
# "Trishuli Hydropower Project-Powerhouse" -> "Trishuli-Powerhouse".
GENERIC_HP_WORDS = re.compile(r"\s*\b(?:Hydroelectric|Hydropower)\b(?:\s+Project\b)?\s*")


def hp_label(name):
    return GENERIC_HP_WORDS.sub(" ", name).replace(" -", "-").strip()


def read(key):
    if key == "hot_bridges" and not HOT_BRIDGES.exists():
        download_hot_bridges()
    return gpd.read_file(PATHS[key]).to_crs(UTM)


def download_hot_bridges():
    HOT_BRIDGES.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(HOT_BRIDGES_URL, HOT_BRIDGES)


def dissolve(gdf):
    """Repair and merge a polygon layer into one valid geometry."""
    return shapely.make_valid(unary_union(shapely.make_valid(gdf.geometry.values))).buffer(0)


class FlowPath:
    """Linear reference along the portal's elevation-profile flow line."""

    def __init__(self):
        ep = json.loads(PATHS["profile"].read_text(encoding="utf-8"))
        self.profile = ep
        self.line = gpd.GeoSeries([LineString(zip(ep["lon"], ep["lat"]))], crs=4326).to_crs(UTM).iloc[0]
        v = np.asarray(self.line.coords)
        self._cum_m = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(v, axis=0).T))])
        self._km = np.asarray(ep["distance_km"])

    def _to_km(self, metres):
        return np.interp(metres, self._cum_m, self._km)

    def km_of(self, geoms):
        """km from source for points, or for the representative point of other geometries."""
        geoms = np.asarray(geoms)
        pts = np.where(shapely.get_type_id(geoms) == 0, geoms, shapely.point_on_surface(geoms))
        return self._to_km(shapely.line_locate_point(self.line, pts))

    def point_at(self, km):
        return shapely.line_interpolate_point(self.line, np.interp(km, self._km, self._cum_m))

    def line_until(self, km):
        return shapely.ops.substring(self.line, 0, float(np.interp(km, self._km, self._cum_m)))

    def line_length_by_bin(self, gdf, edges, step=20.0):
        """Length (km) of line features per distance bin, splitting long lines every `step` metres."""
        out = np.zeros(len(edges) - 1)
        for geom in gdf.geometry.dropna():
            for part in getattr(geom, "geoms", [geom]):
                if part.is_empty:
                    continue
                n = max(int(part.length // step), 1)
                d = np.linspace(0, part.length, n + 1)
                mids = shapely.line_interpolate_point(part, (d[:-1] + d[1:]) / 2)
                out += np.histogram(self._to_km(shapely.line_locate_point(self.line, mids)), bins=edges)[0] * part.length / n
        return out / 1000

    def area_by_bin(self, geom, edges, step=10.0):
        """Area (m2) of a polygon per distance bin, by sampling a `step`-metre grid."""
        shapely.prepare(geom)
        minx, miny, maxx, maxy = geom.bounds
        xs, ys = np.arange(minx, maxx, step), np.arange(miny, maxy, step)
        hist = np.zeros(len(edges) - 1)
        for i in range(0, len(ys), 300):
            X, Y = np.meshgrid(xs, ys[i:i + 300])
            X, Y = X.ravel(), Y.ravel()
            inside = shapely.contains_xy(geom, X, Y)
            if inside.any():
                km = self._to_km(shapely.line_locate_point(self.line, shapely.points(X[inside], Y[inside])))
                hist += np.histogram(km, bins=edges)[0]
        return hist * step * step


def iit_buildings(dedupe_m=0.0):
    """IIT building points. With dedupe_m > 0, drop no-ID points that sit within dedupe_m metres
    of an ID'd point (likely the same building added twice from Google Open Buildings)."""
    b = read("iit_buildings")
    if dedupe_m <= 0:
        return b
    has_id, no_id = b[b.id.notna()], b[b.id.isna()]
    nn = gpd.sjoin_nearest(no_id[["geometry"]], has_id[["geometry"]], distance_col="d")
    dup = nn.index[nn.d <= dedupe_m].unique()
    return b.drop(index=dup)


def harmonised_bridges(path, match_m=100.0):
    """IIT bridges (status normalised) matched to the HOT snapshot, plus HOT-only bridges.

    Returns (iit, hot_only, union) where union has one row per bridge site with columns
    status (Destroyed / Damaged / Intact / No info), km, source.
    IIT status is kept; HOT status fills IIT "No info" when a HOT bridge lies within match_m.
    """
    iit = read("iit_bridges")
    hot = read("hot_bridges")
    iit["status_iit"] = iit.descriptio.map(IIT_STATUS)
    hot["status_h"] = hot.status.map(HOT_STATUS)
    near = [int(np.argmin(hot.distance(p).values)) for p in iit.geometry]
    iit["hot_dist_m"] = [hot.geometry.iloc[i].distance(p) for i, p in zip(near, iit.geometry)]
    matched = iit.hot_dist_m <= match_m
    iit["hot_name"] = [hot["name"].iloc[i] if m else None for i, m in zip(near, matched)]
    iit["status_hot"] = [hot.status_h.iloc[i] if m else None for i, m in zip(near, matched)]
    iit["agreement"] = np.select(
        [~matched, iit.status_iit == "No info", iit.status_iit == iit.status_hot],
        ["IIT only", "IIT no info", "agree"], "conflict")
    iit["status"] = np.where((iit.status_iit == "No info") & matched, iit.status_hot, iit.status_iit)
    iit["km"] = path.km_of(iit.geometry)
    hot_only = hot[[iit.distance(p).min() > match_m for p in hot.geometry]].copy()
    hot_only["status"] = hot_only.status_h
    hot_only["km"] = path.km_of(hot_only.geometry)
    union = pd.concat([iit.assign(source="IIT")[["status", "km", "source"]],
                       hot_only.assign(source="HOT")[["status", "km", "source"]]], ignore_index=True)
    return iit, hot_only, union


def hydropower(path):
    """OSM working-group hydropower structures (empty geometries dropped) plus Upper Trishuli-2."""
    hp = read("hydropower")
    hp = hp[~hp.geometry.is_empty & (hp.area > 0)][["Name", "Damage_Sta", "geometry"]].copy()
    ut2 = gpd.GeoDataFrame({"Name": ["Upper Trishuli-2 Hydropower Project"], "Damage_Sta": ["Fully damaged"]},
                           geometry=[Point(*UPPER_TRISHULI_2)], crs=4326).to_crs(UTM)
    hp = pd.concat([hp, ut2], ignore_index=True)
    hp["km"] = path.km_of(hp.geometry)
    hp["label"] = hp.Name.map(hp_label)
    return hp.sort_values("km")
