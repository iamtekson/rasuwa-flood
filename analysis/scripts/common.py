"""Shared paths, loaders and the flow-path linear reference for the Rasuwa damage analysis.

Folder layout (relative to analysis/):
  inputs/        analysis-specific inputs: flow path line, frozen HOT bridge snapshot, inset frames
  intermediate/  layers and tables derived by build_intermediate.py
  outputs/       figures and other deliverables
Repo-wide damage layers are read in place from data/.

Every distance is "km from source": the length along inputs/flow_path/flow_path_line.shp
(EPSG:32645), measured from its upstream end.
"""
import re
import urllib.request
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import Point
from shapely.ops import unary_union

warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", "GeoSeries.notna", UserWarning)

ANALYSIS = Path(__file__).resolve().parents[1]
ROOT = ANALYSIS.parent
INPUTS = ANALYSIS / "inputs"
INTERMEDIATE = ANALYSIS / "intermediate"
OUTPUTS = ANALYSIS / "outputs"
DATA = ROOT / "data"
IIT = DATA / "Impact-Assessment-Shashi-Ashim"
OSM = DATA / "OSM"
UTM = 32645  # WGS 84 / UTM zone 45N

# HOT bridge damage is live on S3 and keeps changing; the analysis uses a frozen snapshot.
HOT_BRIDGES_URL = "https://production-raw-data-api.s3.amazonaws.com/ISO3/NPL/combined/hot_flood_npl_bridge_damage.geojson"

PATHS = {
    # analysis inputs
    "flow_path": INPUTS / "flow_path" / "flow_path_line.shp",
    "inset_frames": INPUTS / "inset_frames.geojson",
    "hot_bridges": INPUTS / "hot_bridge_damage_2026-10-14.geojson",
    # repo data
    "dem": DATA / "tiff" / "dem_2km_buffer.tif",
    "cities": DATA / "cities.geojson",
    "inundation": IIT / "Inundation" / "Inundation.shp",  # final flood inundation (Shashi & Ashim)
    "iit_buildings": IIT / "Builidngs" / "Buildings.shp",
    "iit_roads": IIT / "Impacted_Road" / "Damage_Road.shp",
    "iit_bridges": IIT / "Bridges" / "Bridges.shp",
    "hydropower": OSM / "13. Hydropower" / "Hydropower_ar_29Aug.geojson",
    # The OSM road network comes in three non-overlapping pieces: road inside the OSM working-group
    # flood extent, road within 100 m of it, and everything else ("Complete Road").
    "roads_damaged": OSM / "4. Road Network" / "Road_damaged.geojson",
    "roads_endangered": OSM / "4. Road Network" / "Road_endangered.geojson",
    "roads_rest": OSM / "4. Road Network" / "Complete Road.geojson",
    # used only by compare_datasets.py
    "portal_extent": DATA / "flood_extent_v2.geojson",
    "hot_extent": DATA / "hot_flood_npl_flood_extent.geojson",
    "osm_extent": OSM / "1. Area_of_interest_flooded_area" / "flood_extent_Extended_31th_August.geojson",
    "settlements": OSM / "19. Settlements" / "final_settelement_with_updated_v2.geojson",
    "portal_buildings": DATA / "buildings_essential.geojson",
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
    if key == "hot_bridges" and not PATHS[key].exists():
        urllib.request.urlretrieve(HOT_BRIDGES_URL, PATHS[key])
    g = gpd.read_file(PATHS[key]).to_crs(UTM)
    return g[g.geometry.notna() & ~g.geometry.is_empty]


def dissolve(gdf):
    """Repair and merge a polygon layer into one valid geometry."""
    return shapely.make_valid(unary_union(shapely.make_valid(gdf.geometry.values))).buffer(0)


def inundation():
    return dissolve(read("inundation"))


def road_network():
    """The full OSM road network (the three pieces concatenated), with `highway` and `road_class`."""
    roads = pd.concat([read(k)[["highway", "geometry"]] for k in ("roads_damaged", "roads_endangered", "roads_rest")],
                      ignore_index=True)
    roads["road_class"] = np.where(roads.highway.isin(MAIN_ROADS), "main", "local")
    return gpd.GeoDataFrame(roads, crs=UTM)


class FlowPath:
    """Linear reference: km = length along the flow-path line from its upstream end."""

    def __init__(self):
        self.line = shapely.line_merge(shapely.union_all(read("flow_path").geometry.values))
        if self.line.geom_type != "LineString":
            raise ValueError(f"{PATHS['flow_path'].name} must be one continuous line, got {self.line.geom_type}")
        self.length_km = self.line.length / 1000

    def km_of(self, geoms):
        """km from source for points, or for the representative point of other geometries."""
        geoms = np.asarray(geoms)
        pts = np.where(shapely.get_type_id(geoms) == 0, geoms, shapely.point_on_surface(geoms))
        return shapely.line_locate_point(self.line, pts) / 1000

    def offset_m(self, geoms):
        return shapely.distance(self.line, np.asarray(geoms))

    def point_at(self, km):
        return shapely.line_interpolate_point(self.line, np.asarray(km) * 1000)

    def sample_lines(self, gdf, step=20.0, columns=()):
        """Split line features into pieces of about `step` metres: one row per piece with its km
        and length, plus any `columns` carried over from the feature."""
        rows = []
        for rec in gdf.itertuples():
            for part in getattr(rec.geometry, "geoms", [rec.geometry]):
                if part.is_empty or part.length == 0:
                    continue
                n = max(int(part.length // step), 1)
                d = np.linspace(0, part.length, n + 1)
                mids = shapely.line_interpolate_point(part, (d[:-1] + d[1:]) / 2)
                rows.append(pd.DataFrame({"km": shapely.line_locate_point(self.line, mids) / 1000,
                                          "length_m": part.length / n,
                                          **{col: getattr(rec, col) for col in columns}}))
        return pd.concat(rows, ignore_index=True)

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
                km = shapely.line_locate_point(self.line, shapely.points(X[inside], Y[inside])) / 1000
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
    return b.drop(index=nn.index[nn.d <= dedupe_m].unique())


def harmonised_bridges(path, match_m=100.0):
    """IIT bridges (status normalised) matched to the HOT snapshot, plus HOT-only bridges.

    Returns (iit, hot_only, union); union has one row per bridge site with status
    (Destroyed / Damaged / Intact / No info), km and source. IIT status is kept; HOT status
    fills IIT "No info" when a HOT bridge lies within match_m.
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
    union = pd.concat([iit.assign(source="IIT", name=iit.id)[["name", "status", "km", "source", "geometry"]],
                       hot_only.assign(source="HOT")[["name", "status", "km", "source", "geometry"]]],
                      ignore_index=True)
    return iit, hot_only, gpd.GeoDataFrame(union, crs=UTM)


def hydropower(path):
    """OSM working-group hydropower structures (empty geometries dropped) plus Upper Trishuli-2."""
    hp = read("hydropower")
    hp = hp[hp.area > 0][["Name", "Damage_Sta", "geometry"]].copy()
    ut2 = gpd.GeoDataFrame({"Name": ["Upper Trishuli-2 Hydropower Project"], "Damage_Sta": ["Fully damaged"]},
                           geometry=[Point(*UPPER_TRISHULI_2)], crs=4326).to_crs(UTM)
    hp = pd.concat([hp, ut2], ignore_index=True)
    hp["km"] = path.km_of(hp.geometry)
    hp["label"] = hp.Name.map(hp_label)
    return gpd.GeoDataFrame(hp.sort_values("km"), crs=UTM)
