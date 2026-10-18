# /// script
# requires-python = ">=3.10"
# dependencies = ["geopandas>=1.0", "pyogrio", "shapely>=2.0", "pyproj", "matplotlib>=3.8", "numpy", "pandas"]
# ///
"""Damage profile along the flow path (manuscript figure, panel b).

Reads analysis/intermediate/ (run build_intermediate.py first) and writes
analysis/outputs/damage_profile.png/.pdf/.svg.

    uv run analysis/scripts/damage_profile.py
    uv run analysis/scripts/damage_profile.py --utc            # arrival times in UTC instead of Nepal Time
    uv run analysis/scripts/damage_profile.py --no-near        # only road inside the flood inundation
    uv run analysis/scripts/damage_profile.py --no-insets      # no shaded inset bands
    uv run analysis/scripts/damage_profile.py --hp-labels      # name each hydropower marker
"""
import argparse
import json
from datetime import datetime, timedelta

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

import common as c

# Towns marked on the elevation track (names as in intermediate/towns.csv).
TOWNS = ["Rasuwagadhi", "Syabrubesi", "Betrawati", "Bidur", "Devighat", "Malekhu", "Mugling"]
NPT_OFFSET = timedelta(hours=5, minutes=45)  # Nepal Time = UTC+05:45
HP_LABEL_GAP_KM = 4.8  # minimum spacing between hydropower labels (with --hp-labels)

INK, INK2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
BAND = "#e9e2cc"  # inset bands: warm tint so they read as "zoomed in", not as data
MAIN, LOCAL, NEAR = "#3d3c39", "#b9b7ae", "#ffffff"
STATUS = {"Destroyed": "#d03b3b", "Damaged": "#ec835a", "Intact": "#898781", "No info": "#c3c2b7"}


def spread(anchors, gap):
    """Label positions as close to `anchors` as possible while at least `gap` apart, order kept.
    Labels that would collide are merged into a group centred on the mean of their anchors."""
    order = np.argsort(anchors)
    groups = [[a] for a in np.asarray(anchors, float)[order]]
    start = lambda g: np.mean(g) - (len(g) - 1) * gap / 2
    merged = True
    while merged:
        merged = False
        for i in range(len(groups) - 1):
            if start(groups[i]) + len(groups[i]) * gap > start(groups[i + 1]):
                groups[i] += groups.pop(i + 1)
                merged = True
                break
    pos = np.empty(len(order))
    pos[order] = np.concatenate([start(g) + gap * np.arange(len(g)) for g in groups])
    return pos


def load():
    d = c.INTERMEDIATE
    if not (d / "build_info.json").exists():
        raise SystemExit("analysis/intermediate/ is empty: run analysis/scripts/build_intermediate.py first")
    return {
        "info": json.loads((d / "build_info.json").read_text(encoding="utf-8")),
        "elev": pd.read_csv(d / "elevation_profile.csv"),
        "towns": pd.read_csv(d / "towns.csv"),
        "buildings": pd.read_csv(d / "buildings.csv"),
        "roads": pd.read_csv(d / "road_pieces.csv"),
        "bridges": gpd.read_file(d / "bridges.geojson"),
        "hp": gpd.read_file(d / "hydropower.geojson"),
        "bands": pd.read_csv(d / "inset_bands.csv"),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bin", type=float, default=5, help="bin width in km (default 5)")
    ap.add_argument("--xmax", type=float, default=165, help="last km shown (default 165, just past Mugling)")
    ap.add_argument("--utc", action="store_true", help="show flood arrival times in UTC (default Nepal Time, UTC+05:45)")
    ap.add_argument("--no-near", action="store_true", help="leave out road just outside the flood inundation")
    ap.add_argument("--no-insets", action="store_true", help="leave out the shaded inset bands")
    ap.add_argument("--hp-labels", action="store_true", help="name each hydropower marker (default: markers only)")
    ap.add_argument("--full-hp-names", action="store_true", help="with --hp-labels, use the full names from the layer")
    ap.add_argument("--out", default=str(c.OUTPUTS / "damage_profile"), help="output path without extension")
    args = ap.parse_args()

    D = load()
    near_m = D["info"]["near_m"]
    edges = np.arange(0, args.xmax + args.bin, args.bin)
    n_bld = np.histogram(D["buildings"].km, bins=edges)[0]
    roads = D["roads"]

    def road_km(sel):
        return np.histogram(roads.km[sel], bins=edges, weights=roads.length_m[sel])[0] / 1000

    r_main = road_km((roads.zone == "in") & (roads.road_class == "main"))
    r_local = road_km((roads.zone == "in") & (roads.road_class == "local"))
    r_near = np.zeros_like(r_main) if args.no_near else road_km(roads.zone == "near")
    bridges, hp = D["bridges"], D["hp"]
    bands = [] if args.no_insets else list(D["bands"].itertuples())

    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Arial", "Segoe UI", "DejaVu Sans"],
                         "font.size": 7, "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": MUTED,
                         "ytick.color": MUTED, "axes.linewidth": 0.6, "xtick.major.width": 0.6,
                         "ytick.major.width": 0.6, "hatch.linewidth": 0.5, "hatch.color": "#8c8a83"})
    hp_track = 1.35 if args.hp_labels else 0.45  # labels need room above the markers
    fig, axs = plt.subplots(5, 1, figsize=(7.09, 4.5 + hp_track - 0.45), sharex=True,
                            gridspec_kw={"height_ratios": [1.0, 0.85, 0.85, hp_track, 0.45], "hspace": 0.14})
    for ax in axs:
        ax.set_xlim(0, args.xmax)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.grid(axis="y", color=GRID, lw=0.5)
        ax.set_axisbelow(True)
        for b in bands:
            ax.axvspan(b.km_from, b.km_to, color=BAND, zorder=0, lw=0)
        ax.tick_params(length=2.5)

    def total(ax, text):
        ax.text(1.005, 0.5, text, transform=ax.transAxes, ha="left", va="center", fontsize=6.5, color=INK, fontweight="bold")

    def bars(ax, y, bottom=0, **kw):
        ax.bar(edges[:-1], y, bottom=bottom, width=args.bin, align="edge", edgecolor="white", linewidth=0.8, **kw)

    def strip(ax, label):
        ax.grid(False)
        ax.spines["left"].set_visible(False)
        ax.set_yticks([0])
        ax.set_yticklabels([label], fontsize=6.5, color=INK2)
        ax.tick_params(axis="y", length=0)

    # elevation, towns, flood arrival times
    ax = axs[0]
    e = D["elev"][D["elev"].km <= args.xmax]
    ax.fill_between(e.km, 0, e.elevation_m, color="#efeee9", lw=0, zorder=0.5)
    ax.plot(e.km, e.elevation_m, color=INK2, lw=1, zorder=2)
    ax.set_ylim(0, 6000)
    ax.set_yticks([0, 2000, 4000])
    ax.set_ylabel("Elevation (m)")
    towns = D["towns"].drop_duplicates("name").set_index("name")
    for name in TOWNS:
        if name not in towns.index:
            print(f"town not found near the flow path: {name}")
            continue
        k, t = towns.at[name, "km"], towns.at[name, "arrival_npt"]
        if isinstance(t, str) and args.utc:
            t = (datetime.strptime(t, "%H:%M") - NPT_OFFSET).strftime("%H:%M")
        zz = np.interp(k, e.km, e.elevation_m)
        ax.plot([k, k], [zz, zz + 350], color=MUTED, lw=0.5, zorder=2)
        ax.text(k, zz + 420, name + (f" {t}" if isinstance(t, str) else ""), rotation=90, ha="center", va="bottom",
                fontsize=5.8, color=INK2, zorder=3)
    ax.text(0.995, 0.96, f"Flood arrival times in {'UTC' if args.utc else 'Nepal Time (UTC+05:45)'}",
            transform=ax.transAxes, ha="right", va="top", fontsize=5.8, color=INK2)
    ax.annotate("source", xy=(0.3, e.elevation_m.iloc[0]), xytext=(3, 4600), fontsize=5.8, color=INK2, va="bottom",
                arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.5))
    for b in bands:  # letters at the band's right edge stay clear of the vertical town labels
        ax.text(b.km_to - 0.4, 6150, b.panel, ha="right", va="bottom", fontsize=8, fontweight="bold", color=INK, clip_on=False)

    # buildings
    ax = axs[1]
    bars(ax, n_bld, color=MAIN)
    ax.set_ylabel(f"Buildings in\nflood inundation\n(per {args.bin:g} km)")
    pk = int(np.argmax(n_bld))
    ax.set_ylim(0, n_bld[pk] * 1.18)
    ax.text(edges[pk] + args.bin / 2, n_bld[pk] * 1.02, f"{n_bld[pk]:,}", ha="center", va="bottom", fontsize=5.8, color=INK2)
    total(ax, f"{n_bld.sum():,}\nbuildings")

    # roads
    ax = axs[2]
    bars(ax, r_main, color=MAIN, label="Highways & main roads")
    bars(ax, r_local, bottom=r_main, color=LOCAL, label="Local roads & tracks")
    road_text = f"{r_main.sum() + r_local.sum():.0f} km in\nflood inundation\n({r_main.sum():.0f} km main)"
    ylabel = f"Road in flood\ninundation\n(km per {args.bin:g} km)"
    if not args.no_near:
        ax.bar(edges[:-1], r_near, bottom=r_main + r_local, width=args.bin, align="edge", color=NEAR,
               edgecolor="#8c8a83", linewidth=0.5, hatch="//////", label=f"Within {near_m:g} m of flood inundation")
        road_text = (f"{r_main.sum() + r_local.sum():.0f} km in flood\ninundation ({r_main.sum():.0f} km main)\n"
                     f"+{r_near.sum():.0f} km within {near_m:g} m")
        ylabel = f"Road length\n(km per {args.bin:g} km)"
    ax.set_ylabel(ylabel)
    ax.set_ylim(0, (r_main + r_local + r_near).max() * 1.45)  # headroom for the legend
    ax.legend(loc="upper right", frameon=False, fontsize=6, handlelength=1.0, handleheight=0.8)
    total(ax, road_text)

    # hydropower: markers only by default; with --hp-labels, one label per mapped structure from the
    # layer's Name field, spread so labels never overlap, with a leader line to its marker
    ax = axs[3]
    strip(ax, "Hydropower")
    ax.set_ylim(*((-0.4, 3.6) if args.hp_labels else (-0.6, 0.6)))
    ax.scatter(hp.km, np.zeros(len(hp)), marker="s", s=24, facecolor=STATUS["Destroyed"], edgecolor="white", lw=0.6, zorder=3)
    if args.hp_labels:
        labels = hp.Name if args.full_hp_names else hp.label
        for k, lx, name in zip(hp.km, spread(hp.km.values, HP_LABEL_GAP_KM), labels):
            ax.plot([k, k, lx], [0.18, 0.5, 1.1], color=MUTED, lw=0.5, zorder=2)  # vertical stem, then to label
            ax.text(lx, 1.17, name, rotation=45, rotation_mode="anchor", ha="left", va="bottom",
                    fontsize=5.6, color=INK2, clip_on=False)
    total(ax, f"{len(hp)} hydropower\nstructures")

    # bridges
    ax = axs[4]
    strip(ax, "Bridges")
    ax.set_ylim(-0.6, 0.6)
    rng = np.random.default_rng(3)  # vertical jitter only, so nearby bridges stay visible
    order = ["Intact", "No info", "Damaged", "Destroyed"]
    for st in order:
        sub = bridges[bridges.status == st]
        filled = st in ("Destroyed", "Damaged")
        ax.scatter(sub.km, rng.uniform(-0.3, 0.3, len(sub)), marker="o" if st == "No info" else "v",
                   s=7 if st == "No info" else 20, facecolor=STATUS[st] if filled else "white",
                   edgecolor="white" if filled else MUTED, linewidth=0.5, zorder=3 + order.index(st))
    counts = bridges.status.value_counts()
    total(ax, f"{counts.get('Destroyed', 0) + counts.get('Damaged', 0)} bridges\ndestroyed or damaged")
    ax.set_xlabel("Distance from source along the flow path (km)", color=INK2)
    ticks = np.arange(0, args.xmax + 1, 10)
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{k:g}" if k % 20 == 0 else "" for k in ticks])
    handles = [
        Line2D([], [], marker="s", ls="", mfc=STATUS["Destroyed"], mec="white", ms=5, label="Hydropower structure, fully damaged"),
        Line2D([], [], marker="v", ls="", mfc=STATUS["Destroyed"], mec="white", ms=5.5,
               label=f"Bridge destroyed, washed away ({counts.get('Destroyed', 0)})"),
        Line2D([], [], marker="v", ls="", mfc=STATUS["Damaged"], mec="white", ms=5.5,
               label=f"Bridge damaged, needs repair ({counts.get('Damaged', 0)})"),
        Line2D([], [], marker="v", ls="", mfc="white", mec=MUTED, ms=5, label=f"Bridge intact ({counts.get('Intact', 0)})"),
        Line2D([], [], marker="o", ls="", mfc="white", mec=MUTED, ms=3, label=f"No information ({counts.get('No info', 0)})"),
    ]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -1.15), ncol=3, frameon=False, fontsize=6,
              handletextpad=0.25, columnspacing=1.2)
    fig.align_ylabels(axs)

    out = c.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf", "svg"):
        fig.savefig(out.with_suffix(f".{ext}"), dpi=400, bbox_inches="tight", facecolor="white")
    print(f"buildings {n_bld.sum():,} | road in inundation {r_main.sum() + r_local.sum():.1f} km (main {r_main.sum():.1f}) | "
          f"within {near_m:g} m {r_near.sum():.1f} km | bridges {counts.to_dict()} | hydropower {len(hp)}")
    print(f"wrote {out}.png/.pdf/.svg")


if __name__ == "__main__":
    main()
