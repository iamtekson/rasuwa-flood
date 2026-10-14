# /// script
# requires-python = ">=3.10"
# dependencies = ["geopandas>=1.0", "pyogrio", "shapely>=2.0", "pyproj", "matplotlib>=3.8", "numpy", "pandas"]
# ///
"""Damage profile along the flow path (manuscript figure, panel b).

Tracks, top to bottom: elevation with towns and flood arrival times; buildings in the flood
zone; road length in the flood zone (plus, optionally, road within 100 m of the flood edge);
hydropower structures and bridges by damage status.

    uv run analysis/damage_profile.py                 # default figure
    uv run analysis/damage_profile.py --no-endangered # damaged roads only
    uv run analysis/damage_profile.py --no-insets     # no shaded inset bands
    uv run analysis/damage_profile.py --dedupe-m 3    # drop likely duplicate IIT buildings
    uv run analysis/damage_profile.py --hp-labels     # name each hydropower marker
"""
import argparse

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

import common as c

# Map insets (c-e) the profile points to: (letter, start km, end km, place). Edit to match your insets.
INSETS = [("c", 20, 27, "Rasuwagadhi-Timure"), ("d", 54, 66, "Upper Trishuli hydropower"),
          ("e", 67, 81, "Betrawati-Trishuli-Bidur")]
# Towns on the elevation track: (label, km). Arrival times come from the profile where known.
TOWNS = [("Rasuwagadhi", 22.0), ("Syabrubesi", 37.6), ("Betrawati", 68.0), ("Bidur", 79.5),
         ("Devighat", 85.7), ("Malekhu", 126.5), ("Mugling", 166.7)]
HP_LABEL_GAP_KM = 4.8  # minimum spacing between hydropower labels; raise it if labels touch
BORDER_KM = 22.0  # China-Nepal border at Rasuwagadhi (dotted line)

INK, INK2, MUTED, GRID, AXIS, BAND = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#f3f2ee"
MAIN, LOCAL, ENDANGERED = "#3d3c39", "#b9b7ae", "#ffffff"
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


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bin", type=float, default=5, help="bin width in km (default 5)")
    ap.add_argument("--xmax", type=float, default=170, help="last km shown (default 170)")
    ap.add_argument("--no-endangered", action="store_true", help="leave out road within 100 m of the flood edge")
    ap.add_argument("--no-insets", action="store_true", help="leave out the shaded inset bands")
    ap.add_argument("--dedupe-m", type=float, default=0.0, help="drop no-ID IIT buildings within this many m of an ID'd one")
    ap.add_argument("--hp-labels", action="store_true", help="name each hydropower marker (default: markers only)")
    ap.add_argument("--full-hp-names", action="store_true",
                    help="with --hp-labels, use the layer's full Name (default drops 'Hydropower Project' etc.)")
    ap.add_argument("--out", default=str(c.OUT / "damage_profile"), help="output path without extension")
    args = ap.parse_args()

    path = c.FlowPath()
    edges = np.arange(0, args.xmax + args.bin, args.bin)

    bld = c.iit_buildings(args.dedupe_m)
    n_bld = np.histogram(path.km_of(bld.geometry), bins=edges)[0]
    dmg = c.read("roads_damaged")
    r_main = path.line_length_by_bin(dmg[dmg.highway.isin(c.MAIN_ROADS)], edges)
    r_local = path.line_length_by_bin(dmg[~dmg.highway.isin(c.MAIN_ROADS)], edges)
    r_end = np.zeros_like(r_main) if args.no_endangered else path.line_length_by_bin(c.read("roads_endangered"), edges)
    _, _, bridges = c.harmonised_bridges(path)
    hp = c.hydropower(path)
    insets = [] if args.no_insets else INSETS

    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Arial", "Segoe UI", "DejaVu Sans"],
                         "font.size": 7, "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": MUTED,
                         "ytick.color": MUTED, "axes.linewidth": 0.6, "xtick.major.width": 0.6,
                         "ytick.major.width": 0.6, "hatch.linewidth": 0.5, "hatch.color": "#8c8a83"})
    hp_track = 1.35 if args.hp_labels else 0.45  # labels need room above the markers
    fig, axs = plt.subplots(5, 1, figsize=(7.09, 4.4 + hp_track - 0.45), sharex=True,
                            gridspec_kw={"height_ratios": [1.0, 0.85, 0.85, hp_track, 0.45], "hspace": 0.14})
    for ax in axs:
        ax.set_xlim(0, args.xmax)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.grid(axis="y", color=GRID, lw=0.5)
        ax.set_axisbelow(True)
        for _, a, b, _ in insets:
            ax.axvspan(a, b, color=BAND, zorder=0, lw=0)
        ax.axvline(BORDER_KM, color=MUTED, lw=0.6, ls=(0, (1, 1.5)), zorder=1)
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

    # elevation, towns, arrival times
    ax = axs[0]
    d, z = np.asarray(path.profile["distance_km"]), np.asarray(path.profile["elevation_m"])
    m = d <= args.xmax
    ax.fill_between(d[m], 0, z[m], color="#e9e8e2", lw=0)
    ax.plot(d[m], z[m], color=INK2, lw=1)
    ax.set_ylim(0, 6000)
    ax.set_yticks([0, 2000, 4000])
    ax.set_ylabel("Elevation (m)")
    arrival = {round(t["distance_km"], 1): t.get("flood_time") for t in path.profile["cities"]}
    for name, k in TOWNS:
        zz = np.interp(k, d, z)
        t = arrival.get(round(k, 1))
        ax.plot([k, k], [zz, zz + 350], color=MUTED, lw=0.5)
        ax.text(k, zz + 420, name + (f" {t[:5]}" if t else ""), rotation=90, ha="center", va="bottom", fontsize=5.8, color=INK2)
    ax.annotate("source", xy=(0.3, z[0]), xytext=(3, 4600), fontsize=5.8, color=INK2, va="bottom",
                arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.5))
    for lab, a, b, _ in insets:
        x = 25.5 if (a <= BORDER_KM <= b) else (a + b) / 2  # keep the letter clear of the Rasuwagadhi label
        ax.text(x, 6150, lab, ha="center", va="bottom", fontsize=8, fontweight="bold", color=INK, clip_on=False)

    # buildings
    ax = axs[1]
    bars(ax, n_bld, color=MAIN)
    ax.set_ylabel(f"Buildings in\nflood zone\n(per {args.bin:g} km)")
    pk = int(np.argmax(n_bld))
    ax.text(edges[pk + 1] + 1, n_bld[pk] * 0.92, f"{n_bld[pk]:,} at km {edges[pk]:g}-{edges[pk + 1]:g}",
            fontsize=5.8, color=INK2, va="top")
    total(ax, f"{n_bld.sum():,}\nbuildings")

    # roads
    ax = axs[2]
    bars(ax, r_main, color=MAIN, label="Highways & main roads")
    bars(ax, r_local, bottom=r_main, color=LOCAL, label="Local roads & tracks")
    road_text = f"{r_main.sum() + r_local.sum():.0f} km\nroad\n({r_main.sum():.0f} km main)"
    ylabel = f"Road in\nflood zone\n(km per {args.bin:g} km)"
    if not args.no_endangered:
        ax.bar(edges[:-1], r_end, bottom=r_main + r_local, width=args.bin, align="edge", color=ENDANGERED,
               edgecolor="#8c8a83", linewidth=0.5, hatch="//////", label="Within 100 m of flood edge")
        road_text = f"{r_main.sum() + r_local.sum():.0f} km in zone\n({r_main.sum():.0f} km main)\n+{r_end.sum():.0f} km within 100 m"
        ylabel = f"Road length\n(km per {args.bin:g} km)"
    ax.set_ylabel(ylabel)
    ax.set_ylim(0, (r_main + r_local + r_end).max() * 1.45)  # headroom for the legend
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
        Line2D([], [], marker="v", ls="", mfc=STATUS["Destroyed"], mec="white", ms=5.5, label=f"Bridge destroyed ({counts.get('Destroyed', 0)})"),
        Line2D([], [], marker="v", ls="", mfc=STATUS["Damaged"], mec="white", ms=5.5, label=f"Bridge damaged ({counts.get('Damaged', 0)})"),
        Line2D([], [], marker="v", ls="", mfc="white", mec=MUTED, ms=5, label=f"Bridge intact ({counts.get('Intact', 0)})"),
        Line2D([], [], marker="o", ls="", mfc="white", mec=MUTED, ms=3, label=f"No information ({counts.get('No info', 0)})"),
    ]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -1.15), ncol=5, frameon=False, fontsize=6,
              handletextpad=0.25, columnspacing=1.0)
    fig.align_ylabels(axs)

    out = c.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf", "svg"):
        fig.savefig(out.with_suffix(f".{ext}"), dpi=400, bbox_inches="tight", facecolor="white")
    print(f"buildings {n_bld.sum():,} | roads in zone {r_main.sum() + r_local.sum():.1f} km "
          f"(main {r_main.sum():.1f}) | within 100 m {r_end.sum():.1f} km | bridges {counts.to_dict()} | "
          f"hydropower structures {len(hp)}")
    print(f"wrote {out}.png/.pdf/.svg")


if __name__ == "__main__":
    main()
