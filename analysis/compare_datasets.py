# /// script
# requires-python = ">=3.10"
# dependencies = ["geopandas>=1.0", "pyogrio", "shapely>=2.0", "pyproj", "matplotlib>=3.8", "numpy", "pandas"]
# ///
"""Compare the IIT Bhubaneswar impact data with the portal data (OSM working group / HOT).

    uv run analysis/compare_datasets.py

Prints the numbers used in the "Rasuwa Flood Damage Data Comparison" report and writes to
analysis/output/:
  comparison_profile.png/.pdf       flooded width, buildings and roads per 5 km, both sources
  flood_extent_agreement.geojson    parts of the flood extent mapped by IIT only, portal only, or both
"""
import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shapely

import common as c

C_IIT, C_PORTAL = "#6250d6", "#1baf7a"  # validated pair (CVD dE 27); aqua needs direct labels
INK, INK2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"


def section(title):
    print(f"\n== {title}")


def main():
    c.OUT.mkdir(parents=True, exist_ok=True)
    path = c.FlowPath()
    edges10 = np.arange(0, 180, 10)

    section("Flood extent")
    raw = c.read("iit_inundation")
    iit = c.dissolve(raw)
    portal = c.dissolve(c.read("portal_extent"))
    hot = c.dissolve(c.read("hot_extent"))
    print(f"IIT: {iit.area / 1e6:.1f} km2 (attribute Shape_Area {raw.Shape_Area.sum() / 1e6:.2f} km2, valid: {raw.is_valid.tolist()})")
    print(f"portal: {portal.area / 1e6:.1f} km2 = HOT 27 Aug {hot.area / 1e6:.1f} km2 + {portal.difference(hot).area / 1e6:.1f} km2 added upstream")
    inter = iit.intersection(portal).area
    print(f"IoU {inter / iit.union(portal).area:.2f} | IIT only {(iit.area - inter) / 1e6:.1f} km2 | portal only {(portal.area - inter) / 1e6:.1f} km2")
    a_iit, a_portal = path.area_by_bin(iit, edges10), path.area_by_bin(portal, edges10)
    ratio = pd.Series((a_portal / np.where(a_iit > 0, a_iit, np.nan)).round(2), index=edges10[:-1])
    print("portal / IIT area per 10 km:", ratio.dropna().to_dict())
    gpd.GeoDataFrame({"part": ["IIT only", "portal only", "both"]},
                     geometry=[iit.difference(portal), portal.difference(iit), iit.intersection(portal)],
                     crs=c.UTM).to_crs(4326).to_file(c.OUT / "flood_extent_agreement.geojson")

    section("Buildings")
    b = c.read("iit_buildings")
    no_id = b[b.id.isna()]
    nn = gpd.sjoin_nearest(no_id[["geometry"]], b[b.id.notna()][["geometry"]], distance_col="d")
    nn = nn[~nn.index.duplicated()]
    print(f"IIT points {len(b):,} | no ID {len(no_id):,} | no-ID within 2 / 5 m of an ID'd point: {(nn.d <= 2).sum()} / {(nn.d <= 5).sum()}")
    outside = b.distance(iit)
    print(f"outside IIT polygon: {(outside > 0).sum()} (max {outside.max():.0f} m)")
    sett = c.read("settlements")
    print(f"OSM working-group settlements: exposed {int(sett.Building_e.sum()):,} of {int(sett.Bu_count.sum()):,} buildings")
    pb = c.read("portal_buildings")
    print(f"portal building layer: {len(pb):,} features, {pb.intersects(portal).sum():,} touch the portal extent")
    km_b, km_s = path.km_of(b.geometry), path.km_of(sett.geometry)
    for lo, hi in [(65, 75), (120, 160)]:
        sel = (km_b >= lo) & (km_b < hi)
        sel_s = (km_s >= lo) & (km_s < hi)
        print(f"km {lo}-{hi}: IIT {sel.sum():,} | OSM working group {int(sett.Building_e[sel_s].sum()):,}")

    section("Roads")
    tr, dmg, end = c.read("iit_roads"), c.read("roads_damaged"), c.read("roads_endangered")
    print(f"IIT {tr.length.sum() / 1000:.1f} km ({len(tr)} segments) | portal damaged {dmg.length.sum() / 1000:.1f} km ({len(dmg)}) | "
          f"within 100 m of flood edge {end.length.sum() / 1000:.1f} km")
    print(f"shared segment lengths: {len(set(tr.length_m.round(2)) & set(dmg.length_m.round(2)))} of {len(tr)}")
    print(f"IIT 'Distance' field equals clipped length: {np.allclose(tr.Distance, tr.length)}")
    buf100 = c.dissolve(c.read("osm_extent")).buffer(100)
    for name, g in [("IIT polygon", iit), ("OSM working-group extent + 100 m", buf100)]:
        print(f"share of IIT road length inside {name}: {tr.intersection(g).length.sum() / tr.length.sum():.1%}")
    print(f"IIT road length within IIT polygon + 50 m: {tr.intersection(iit.buffer(50)).length.sum() / 1000:.0f} km")

    section("Bridges")
    iitb, hot_only, union = c.harmonised_bridges(path)
    hot = c.read("hot_bridges")
    print("IIT status:", iitb.status_iit.value_counts().to_dict(), "| HOT status:", hot.status.value_counts().to_dict())
    print("agreement:", iitb.agreement.value_counts().to_dict(), "| HOT-only:", len(hot_only))
    print("conflicts:", ", ".join(f"{r.id} ({r.status_iit} vs HOT {r.status_hot})" for r in iitb[iitb.agreement == "conflict"].itertuples()))
    print("union:", union.status.value_counts().to_dict(), "total", len(union))

    section("Hydropower")
    hp = c.hydropower(path)
    print(hp[["Name", "km"]].round(1).to_string(index=False))

    # figure: three tracks, both sources, common distance axis
    edges = np.arange(0, 175, 5)
    tracks = [
        ("Mean flooded\nwidth (m)", path.area_by_bin(iit, edges) / 5000, path.area_by_bin(portal, edges) / 5000, "IIT", "Portal"),
        ("Buildings\n(per 5 km)", np.histogram(km_b, bins=edges)[0],
         np.histogram(km_s, bins=edges, weights=sett.Building_e.values)[0], f"IIT ({len(b):,})", f"OSM working group ({int(sett.Building_e.sum()):,})"),
        ("Road in flood\nzone (km / 5 km)", path.line_length_by_bin(tr, edges), path.line_length_by_bin(dmg, edges),
         f"IIT ({tr.length.sum() / 1000:.0f} km)", f"Portal ({dmg.length.sum() / 1000:.0f} km)"),
    ]
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Arial", "Segoe UI", "DejaVu Sans"],
                         "font.size": 7, "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": MUTED,
                         "ytick.color": MUTED, "axes.linewidth": 0.6})
    fig, axs = plt.subplots(3, 1, figsize=(7.09, 3.6), sharex=True, gridspec_kw={"hspace": 0.15})
    for ax, (label, y_iit, y_portal, l_iit, l_portal) in zip(axs, tracks):
        ax.set_xlim(0, 170)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.grid(axis="y", color=GRID, lw=0.5)
        ax.set_axisbelow(True)
        ax.axvline(22.0, color=MUTED, lw=0.6, ls=(0, (1, 1.5)))
        ax.stairs(y_iit, edges, color=C_IIT, lw=1.4, label=l_iit)
        ax.stairs(y_portal, edges, color=C_PORTAL, lw=1.4, label=l_portal)
        ax.set_ylabel(label)
        ax.legend(loc="upper right", frameon=False, fontsize=6, handlelength=1.4)
    w = tracks[0]
    axs[0].set_ylim(0, max(w[1][4:].max(), w[2][4:].max()) * 1.3)
    axs[0].text(24, axs[0].get_ylim()[1] * 0.95, f"km 0-20 off scale (up to {w[1][:4].max():.0f} m)", fontsize=5.6, color=MUTED, va="top")
    axs[0].text(21, 15, "CHINA", ha="right", fontsize=5.6, color=MUTED)
    axs[0].text(23, 15, "NEPAL", ha="left", fontsize=5.6, color=MUTED)
    axs[-1].set_xlabel("Distance from source along the flow path (km)", color=INK2)
    fig.align_ylabels(axs)
    for ext in ("png", "pdf"):
        fig.savefig(c.OUT / f"comparison_profile.{ext}", dpi=300, bbox_inches="tight", facecolor="white")
    print(f"\nwrote comparison_profile.png/.pdf and flood_extent_agreement.geojson to {c.OUT}")


if __name__ == "__main__":
    main()
