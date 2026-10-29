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
from matplotlib.patches import Patch, Rectangle

import common as c

# Towns marked on the elevation track (names as in intermediate/towns.csv; times from inputs/arrival_times.csv).
# Devghat (km 194.7, 14:40) is past the end of the axis, so it is left out.
TOWNS = ["Rasuwagadhi", "Syabrubesi", "Betrawati", "Galchi", "Chumlingtar"]
NPT_OFFSET = timedelta(hours=5, minutes=45)  # Nepal Time = UTC+05:45
HP_LABEL_GAP_KM = 4.8  # minimum spacing between hydropower labels (with --hp-labels)
FIG_W_IN = 180 / 25.4  # exactly 180 mm wide, like panels a and c-e, so the combined figure lines up
MARGIN_IN = {"left": 0.82, "right": 1.08, "top": 0.32}  # room for y labels, totals and letters
BOTTOM_IN = {"legend": 0.66, "no_legend": 0.42}            # room for the x axis (and the --legend row)
TRACK_IN = [0.86, 0.45, 0.50, 0.20, 0.22]                 # elevation, buildings, roads, hydropower, bridges
TRACK_GAP = 0.12                                          # gap between tracks, as a share of the mean track height
LETTER_FMT = "({})"                                       # panel letters: (b), and (c)-(e) on the bands
PANEL_LETTER = LETTER_FMT.format("b")
BAND_LETTER_RAISE_PT = 3                                  # (c)-(e) just above the elevation track
FONT = {"base": 8, "tick": 7.5, "label": 7, "total": 7.5, "letter": 10, "band_letter": 9}  # pt

# Open axes (left and bottom only) in a light grey, faint gridlines, a filled elevation profile.
INK, INK2, MUTED = "#0b0b0b", "#4d4d4d", "#808080"
AXIS, GRID = "#c4c4c4", "#e6e6e6"                         # axis lines / ticks, gridlines
AXIS_W = 0.6                                              # pt
ELEV_LINE, ELEV_FILL = "#4d4d4d", "#eeeeee"
BAND = "#D8D9D8"  # zoom bands: warm, so they read as "zoomed in" and stand out on panel (a)'s hillshade
MAIN, LOCAL, NEAR, HATCH = "#333333", "#b3b3b3", "#ffffff", "#8c8c8c"
NEAR_EDGE, NEAR_EDGE_W = "#737373", 0.5                   # border of the "within 100 m" bar segment (pt)
STATUS = {"Destroyed": "#d03b3b", "Damaged": "#ec835a", "Intact": "#8c8c8c", "No info": "#bfbfbf"}


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
    ap.add_argument("--legend", action="store_true",
                    help="add the hydropower/bridge legend under the plot (off by default: the combined figure "
                         "has one shared key)")
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
                         "font.size": FONT["base"], "axes.labelsize": FONT["base"], "xtick.labelsize": FONT["tick"],
                         "ytick.labelsize": FONT["tick"], "axes.edgecolor": AXIS, "axes.linewidth": AXIS_W,
                         "axes.labelcolor": INK2, "xtick.color": AXIS, "ytick.color": AXIS,
                         "xtick.labelcolor": MUTED, "ytick.labelcolor": MUTED,
                         "xtick.major.width": AXIS_W, "ytick.major.width": AXIS_W, "hatch.linewidth": 0.5,
                         "hatch.color": HATCH, "pdf.fonttype": 42})
    tracks = list(TRACK_IN)
    if args.hp_labels:
        tracks[3] = 1.0  # labels need room above the markers
    bottom_in = BOTTOM_IN["legend" if args.legend else "no_legend"]
    fig_h = sum(tracks) * (1 + TRACK_GAP * (len(tracks) - 1) / len(tracks)) + MARGIN_IN["top"] + bottom_in
    fig, axs = plt.subplots(5, 1, figsize=(FIG_W_IN, fig_h), sharex=True,
                            gridspec_kw={"height_ratios": tracks, "hspace": TRACK_GAP})
    fig.subplots_adjust(left=MARGIN_IN["left"] / FIG_W_IN, right=1 - MARGIN_IN["right"] / FIG_W_IN,
                        top=1 - MARGIN_IN["top"] / fig_h, bottom=bottom_in / fig_h)
    fig.text(0.006, 1 - 0.04 / fig_h, PANEL_LETTER, ha="left", va="top", fontsize=FONT["letter"], fontweight="bold",
             color=INK)
    for ax in axs:
        ax.set_xlim(0, args.xmax)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.grid(axis="y", color=GRID, lw=0.5)
        ax.set_axisbelow(True)
        for b in bands:
            ax.axvspan(b.km_from, b.km_to, color=BAND, zorder=0, lw=0)
        ax.tick_params(length=2.5)

    def total(ax, text):
        ax.text(1.012, 0.5, text, transform=ax.transAxes, ha="left", va="center", fontsize=FONT["total"], color=INK,
                fontweight="bold", linespacing=1.15)

    def bars(ax, y, bottom=0, **kw):
        ax.bar(edges[:-1], y, bottom=bottom, width=args.bin, align="edge", edgecolor="white", linewidth=0.8, **kw)

    def strip(ax, label):
        ax.grid(False)
        ax.spines["left"].set_visible(False)
        ax.set_yticks([0])
        ax.set_yticklabels([label], fontsize=FONT["base"], color=INK2)
        ax.tick_params(axis="y", labelcolor=INK2)
        ax.tick_params(axis="y", length=0, pad=4)

    # elevation, towns, flood arrival times
    ax = axs[0]
    e = D["elev"][D["elev"].km <= args.xmax]
    ax.fill_between(e.km, 0, e.elevation_m, color=ELEV_FILL, lw=0, zorder=0.5)
    ax.plot(e.km, e.elevation_m, color=ELEV_LINE, lw=1.0, zorder=2)
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
        ax.plot([k, k], [zz, zz + 250], color=MUTED, lw=0.5, zorder=2)
        # name and time on two lines, so the vertical label stays inside the track at this font size
        ax.text(k, zz + 320, name + (f"\n{t}" if isinstance(t, str) else ""), rotation=90, ha="center", va="bottom",
                fontsize=FONT["label"], color=INK2, zorder=3, linespacing=1.1)
    ax.text(0.995, 0.95, f"Flood arrival times in {'UTC' if args.utc else 'Nepal Time (UTC+05:45)'}",
            transform=ax.transAxes, ha="right", va="top", fontsize=FONT["label"], color=INK2)
    ax.annotate("source", xy=(0.3, e.elevation_m.iloc[0]), xytext=(3, 4900), fontsize=FONT["label"], color=INK2,
                va="bottom", arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.5))
    for b in bands:  # centred over each band, just above the track
        ax.annotate(LETTER_FMT.format(b.panel), xy=((b.km_from + b.km_to) / 2, 1), xycoords=("data", "axes fraction"),
                    xytext=(0, BAND_LETTER_RAISE_PT), textcoords="offset points", ha="center", va="bottom",
                    fontsize=FONT["band_letter"], fontweight="bold", color=INK, annotation_clip=False)

    # buildings
    ax = axs[1]
    bars(ax, n_bld, color=MAIN)
    ax.set_ylabel("Flooded\nbuildings")  # short lines: must fit the track height; the bin is in the x-label
    pk = int(np.argmax(n_bld))
    ax.set_ylim(0, n_bld[pk] * 1.18)
    ax.set_yticks([0, 500, 1000])
    ax.text(edges[pk] + args.bin / 2, n_bld[pk] * 1.02, f"{n_bld[pk]:,}", ha="center", va="bottom",
            fontsize=FONT["label"], color=INK2)
    total(ax, f"{n_bld.sum():,}\nbuildings")

    # roads
    ax = axs[2]
    bars(ax, r_main, color=MAIN, label="Highways & main roads")
    bars(ax, r_local, bottom=r_main, color=LOCAL, label="Local roads & tracks")
    road_text = f"{r_main.sum() + r_local.sum():.0f} km flooded\n({r_main.sum():.0f} km main)"
    ylabel = "Flooded\nroad (km)"
    if not args.no_near:
        # same white edge as the solid bars, so all three segments have the same visible width
        bars(ax, r_near, bottom=r_main + r_local, color=NEAR, hatch="//////", hatchcolor=HATCH)
        road_text = (f"{r_main.sum() + r_local.sum():.0f} km flooded\n({r_main.sum():.0f} km main)\n"
                     f"+{r_near.sum():.0f} km \u2264 {near_m:g} m")
        ylabel = "Road\nlength\n(km)"
    ax.set_ylabel(ylabel)
    ax.set_ylim(0, (r_main + r_local + r_near).max() * 1.8)  # headroom for the legend
    ax.set_yticks([0, 10, 20])
    road_handles = [Patch(facecolor=MAIN, label="Highway & main road"),
                    Patch(facecolor=LOCAL, label="Local road & track")]
    if not args.no_near:
        # outline drawn just inside the white gap, so the segment keeps the same visible width as the solid bars
        pos = ax.get_position()
        pt_x = pos.width * FIG_W_IN * 72 / args.xmax
        pt_y = pos.height * fig_h * 72 / ax.get_ylim()[1]
        inset = 0.8 / 2 + NEAR_EDGE_W / 2  # half the white edge of bars() + half the outline
        for x0, hgt, base in zip(edges[:-1], r_near, r_main + r_local):
            w_, h_ = args.bin - 2 * inset / pt_x, hgt - 2 * inset / pt_y
            if hgt > 0 and h_ > 0:
                ax.add_patch(Rectangle((x0 + inset / pt_x, base + inset / pt_y), w_, h_, fill=False,
                                       edgecolor=NEAR_EDGE, linewidth=NEAR_EDGE_W, zorder=3))
        road_handles.append(Patch(facecolor=NEAR, edgecolor=NEAR_EDGE, linewidth=NEAR_EDGE_W, hatch="//////",
                                  label=f"Within {near_m:g} m of inundation"))
    ax.legend(handles=road_handles, loc="upper right", frameon=False, fontsize=FONT["label"], handlelength=1.1,
              handleheight=0.7, labelspacing=0.2, borderaxespad=0.2, handletextpad=0.5)
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
                    fontsize=FONT["label"] - 0.5, color=INK2, clip_on=False)
    total(ax, f"{len(hp)} structures")

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
    total(ax, f"{counts.get('Destroyed', 0) + counts.get('Damaged', 0)} washed away\nor damaged")
    ax.set_xlabel(f"Distance from source along the flow path (km)    |    bars: totals per {args.bin:g} km", color=INK2)
    ticks = np.arange(0, args.xmax + 1, 10)
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{k:g}" if k % 20 == 0 else "" for k in ticks])
    handles = [
        Line2D([], [], marker="s", ls="", mfc=STATUS["Destroyed"], mec="white", ms=5, label="Hydropower structure damaged"),
        Line2D([], [], marker="v", ls="", mfc=STATUS["Destroyed"], mec="white", ms=5.5,
               label=f"Bridge washed away ({counts.get('Destroyed', 0)})"),
        Line2D([], [], marker="v", ls="", mfc=STATUS["Damaged"], mec="white", ms=5.5,
               label=f"Bridge damaged ({counts.get('Damaged', 0)})"),
        Line2D([], [], marker="v", ls="", mfc="white", mec=MUTED, ms=5, label=f"Bridge intact ({counts.get('Intact', 0)})"),
        Line2D([], [], marker="o", ls="", mfc="white", mec=MUTED, ms=3, label=f"No information ({counts.get('No info', 0)})"),
    ]
    if args.legend:
        plot_mid = (MARGIN_IN["left"] + (FIG_W_IN - MARGIN_IN["right"])) / 2 / FIG_W_IN
        fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(plot_mid, 0.005), ncol=5, frameon=False,
                   fontsize=FONT["label"], handletextpad=0.25, columnspacing=1.1)
    for ax in axs[:3]:
        ax.yaxis.labelpad = 4
    fig.align_ylabels(axs[:3])  # only the numeric tracks: the strip row names are wide and would push every label left

    out = c.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf", "svg"):
        fig.savefig(out.with_suffix(f".{ext}"), dpi=600, facecolor="white")  # fixed 180 mm page, no trimming
    print(f"buildings {n_bld.sum():,} | road in inundation {r_main.sum() + r_local.sum():.1f} km (main {r_main.sum():.1f}) | "
          f"within {near_m:g} m {r_near.sum():.1f} km | bridges {counts.to_dict()} | hydropower {len(hp)}")
    print(f"wrote {out}.png/.pdf/.svg")


if __name__ == "__main__":
    main()
