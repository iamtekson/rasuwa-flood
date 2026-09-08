"""
Static chart + animation rendering for the flood elevation profile.

Design notes (see the `dataviz` skill for the underlying rules):
- Two states are encoded: "flood already reached this point" (critical red)
  vs. "not yet confirmed" (muted grey). Identity lives in a small dot next to
  each label, not in colored text, per the "text never wears the data color"
  rule -- labels use text tokens (primary/secondary/muted ink) only.
- The area under the curve is a vertical gradient anchored to the y-axis (a
  glow that fades from the line down to the surface), the standard modern
  "area chart" treatment, rather than a flat, saturated fill block.
- A stat row under the title carries the headline numbers (drop, distance,
  elapsed time) as label/value tiles, so the chart reads before you even
  look at the curve.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.path import Path as MplPath
from matplotlib.patches import PathPatch

from flood_profile import Stopwatch

# ---------------------------------------------------------------------------
# Palette (validated categorical/status palette -- see dataviz skill)
# ---------------------------------------------------------------------------
SURFACE = "#fcfcfb"
PAGE_PLANE = "#f9f9f7"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"
CRITICAL = "#d03b3b"
ORANGE = "#eb6834"

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Segoe UI", "Arial", "DejaVu Sans"]

_PENDING_CMAP = LinearSegmentedColormap.from_list("pending", ["#f8f7f5", "#dcdad2"])
_REACHED_CMAP = LinearSegmentedColormap.from_list("reached", ["#fdf1ea", "#e8623a"])


def _gradient_fill(ax, x: np.ndarray, y_top: np.ndarray, y_bottom: float, cmap, zorder: float) -> None:
    """Fill under a curve with a vertical gradient (fixed to the y-axis, not
    the curve), clipped to the area between the curve and the baseline.
    """
    if len(x) < 2:
        return
    xmin, xmax = float(x.min()), float(x.max())
    ymin, ymax = ax.get_ylim()
    gradient = np.linspace(0, 1, 256).reshape(-1, 1)
    im = ax.imshow(
        gradient,
        cmap=cmap,
        aspect="auto",
        extent=(xmin, xmax, ymin, ymax),
        origin="lower",
        zorder=zorder,
    )
    verts = np.column_stack([np.concatenate([x, x[::-1]]), np.concatenate([y_top, np.full(len(x), y_bottom)])])
    patch = PathPatch(MplPath(verts), facecolor="none", edgecolor="none")
    ax.add_patch(patch)
    im.set_clip_path(patch)


def _label_shelf_heights(distances: np.ndarray, y_span: float) -> np.ndarray:
    """Stagger label shelf heights (fraction of y_span above the point's own
    elevation) so closely-spaced annotations don't collide.
    """
    tiers = np.array([0.30, 0.48, 0.66, 0.39, 0.57, 0.75])
    order = np.argsort(distances)
    heights = np.empty(len(distances))
    heights[order] = tiers[np.arange(len(distances)) % len(tiers)] * y_span
    return heights


def _stat_row(fig, ax, stats: list[tuple[str, str]]) -> None:
    """A row of (label, value) tiles under the title -- the headline numbers,
    read before the curve itself.
    """
    x = 0.0
    for i, (label, value) in enumerate(stats):
        fig.text(x, 0.885, value, transform=fig.transFigure, ha="left", va="baseline",
                  fontsize=17, fontweight="bold", color=INK_PRIMARY)
        fig.text(x, 0.858, label, transform=fig.transFigure, ha="left", va="baseline",
                  fontsize=9.5, color=INK_MUTED)
        x += 0.145
        if i < len(stats) - 1:
            fig.add_artist(
                plt.Line2D([x - 0.028, x - 0.028], [0.850, 0.905], transform=fig.transFigure,
                           color=GRIDLINE, linewidth=1.2)
            )


def _style_axes(fig, ax, x_max: float, y_min: float, y_max: float) -> None:
    ax.set_xlim(0, x_max)
    ax.set_ylim(y_min, y_max)
    ax.set_facecolor(SURFACE)
    fig.patch.set_facecolor(PAGE_PLANE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    ax.spines["bottom"].set_linewidth(1)
    ax.grid(axis="y", color=GRIDLINE, linewidth=1, zorder=0.5)
    ax.set_axisbelow(True)
    ax.tick_params(axis="both", colors=INK_MUTED, labelsize=10, length=0)
    ax.set_xlabel("Distance along river (km)", color=INK_SECONDARY, fontsize=10.5)
    ax.set_ylabel("Elevation (m)", color=INK_SECONDARY, fontsize=10.5)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:,.0f}")


def _legend(ax) -> None:
    handles = [
        plt.Line2D([0], [0], marker="o", linestyle="", markersize=7, markerfacecolor=CRITICAL,
                   markeredgecolor=SURFACE, markeredgewidth=1.2, label="Flood has passed"),
        plt.Line2D([0], [0], marker="o", linestyle="", markersize=7, markerfacecolor=SURFACE,
                   markeredgecolor=INK_MUTED, markeredgewidth=1.4, label="Not yet reached"),
    ]
    leg = ax.legend(
        handles=handles, loc="upper right", frameon=False, fontsize=10,
        labelcolor=INK_SECONDARY, handletextpad=0.5, borderaxespad=0,
    )
    leg.set_zorder(10)


def _draw_stems(ax, cities: pd.DataFrame, shelf: np.ndarray, y_top_pad: float, reached_mask: np.ndarray):
    for reached, (_, row), h in zip(reached_mask, cities.iterrows(), shelf):
        dot_color = CRITICAL if reached else SURFACE
        dot_edge = SURFACE if reached else INK_MUTED
        text_color = INK_PRIMARY if reached else INK_MUTED
        weight = "semibold" if reached else "normal"
        y0 = row["elevation_m"]
        y1 = row["elevation_m"] + h + y_top_pad
        ax.plot([row["distance_km"]] * 2, [y0, y1], color=GRIDLINE if not reached else "#e7c3bd",
                 linewidth=1.3, zorder=2.5, solid_capstyle="round")
        ax.scatter([row["distance_km"]], [y1], s=46, color=dot_color, edgecolor=dot_edge,
                   linewidth=1.3, zorder=4)
        name = row["name"]
        time_caption = f"{row['flood_time']}  " if isinstance(row["flood_time"], str) else ""
        ax.annotate(
            name,
            xy=(row["distance_km"], y1),
            xytext=(6, 4),
            textcoords="offset points",
            color=text_color,
            fontsize=9.6,
            fontweight=weight,
            va="bottom",
            ha="left",
            zorder=5,
        )
        if time_caption:
            ax.annotate(
                time_caption.strip(),
                xy=(row["distance_km"], y1),
                xytext=(6, 17),
                textcoords="offset points",
                color=INK_MUTED,
                fontsize=8,
                va="bottom",
                ha="left",
                zorder=5,
            )


def _compute_bounds(profile: pd.DataFrame, cities: pd.DataFrame, x_margin_km: float):
    x_max = cities["distance_km"].max() + x_margin_km
    prof = profile[profile.distance_km <= x_max]
    y_min = prof.elevation_m.min()
    y_span = prof.elevation_m.max() - y_min
    shelf = _label_shelf_heights(cities.distance_km.to_numpy(), y_span)
    y_top_pad = y_span * 0.035
    y_max = (cities.elevation_m + shelf).max() + y_top_pad * 5
    return prof, x_max, y_min, y_max, shelf, y_top_pad


def plot_static(
    profile: pd.DataFrame,
    cities: pd.DataFrame,
    out_path: Path,
    title: str,
    subtitle: str | None = None,
    marker_km: float | None = None,
    x_margin_km: float = 15.0,
) -> None:
    if marker_km is None:
        marker_km = cities.loc[cities.flood_reached, "distance_km"].max()

    prof, x_max, y_min, y_max, shelf, y_top_pad = _compute_bounds(profile, cities, x_margin_km)

    fig, ax = plt.subplots(figsize=(16, 9), dpi=150)
    fig.subplots_adjust(top=0.80, bottom=0.09, left=0.06, right=0.975)
    _style_axes(fig, ax, x_max, y_min, y_max)

    _gradient_fill(ax, prof.distance_km.to_numpy(), prof.elevation_m.to_numpy(), y_min, _PENDING_CMAP, zorder=0)
    ax.plot(prof.distance_km, prof.elevation_m, color=BASELINE, linewidth=1.3, zorder=1)

    revealed = prof[prof.distance_km <= marker_km]
    _gradient_fill(ax, revealed.distance_km.to_numpy(), revealed.elevation_m.to_numpy(), y_min, _REACHED_CMAP, zorder=1.2)
    ax.plot(revealed.distance_km, revealed.elevation_m, color="white", linewidth=3.2, zorder=1.4, alpha=0.6)
    ax.plot(revealed.distance_km, revealed.elevation_m, color=CRITICAL, linewidth=2, zorder=1.5)

    reached_mask = cities.distance_km.to_numpy() <= marker_km + 1e-6
    _draw_stems(ax, cities, shelf, y_top_pad, reached_mask)
    _legend(ax)

    marker_elev = np.interp(marker_km, profile.distance_km, profile.elevation_m)
    ax.scatter([marker_km], [marker_elev], s=260, color=CRITICAL, alpha=0.18, zorder=4, linewidth=0)
    ax.scatter([marker_km], [marker_elev], s=90, color=CRITICAL, edgecolor="white", linewidth=1.6, zorder=5)

    watch = Stopwatch.from_annotations(cities, start_km=0.0, start_time=cities.flood_time.dropna().iloc[0])
    elapsed_min = (watch.time_at(marker_km) - watch.control_sec[0]) / 60

    fig.text(0.06, 0.955, title, fontsize=24, fontweight="bold", color=INK_PRIMARY, ha="left", va="baseline")
    if subtitle:
        fig.text(0.06, 0.925, subtitle, fontsize=12.5, color=INK_SECONDARY, ha="left", va="baseline")

    _stat_row(
        fig, ax,
        [
            ("Elevation drop", f"{prof.elevation_m.max() - prof.elevation_m.min():,.0f} m"),
            ("Distance traced", f"{marker_km:,.0f} km"),
            ("Time elapsed", f"{elapsed_min:,.0f} min"),
            ("Last confirmed", Stopwatch.sec_to_hms(watch.time_at(marker_km))),
        ],
    )

    fig.savefig(out_path, facecolor=fig.get_facecolor())
    plt.close(fig)


def build_animation(
    profile: pd.DataFrame,
    cities: pd.DataFrame,
    out_gif: Path,
    title: str,
    subtitle: str | None = None,
    out_mp4: Path | None = None,
    fps: int = 12,
    movement_frames: int = 160,
    pause_seconds_known: float = 1.2,
    pause_seconds_unknown: float = 0.4,
    x_margin_km: float = 15.0,
) -> None:
    from matplotlib.animation import FuncAnimation, PillowWriter

    marker_km = cities.loc[cities.flood_reached, "distance_km"].max()
    prof, x_max, y_min, y_max, shelf, y_top_pad = _compute_bounds(profile, cities, x_margin_km)
    prof = prof.reset_index(drop=True)

    normal_x = np.linspace(0, marker_km, movement_frames)
    movement_x = np.unique(np.concatenate([normal_x, cities.distance_km.to_numpy()]))
    movement_x = movement_x[movement_x <= marker_km + 1e-9]

    watch = Stopwatch.from_annotations(cities, start_km=0.0, start_time=cities.flood_time.dropna().iloc[0])

    timeline = []
    for x in movement_x:
        timeline.append(x)
        hit = cities[np.isclose(cities.distance_km, x, atol=1e-6)]
        for _, row in hit.iterrows():
            pause_s = pause_seconds_known if isinstance(row["flood_time"], str) else pause_seconds_unknown
            timeline.extend([x] * int(round(pause_s * fps)))

    fig, ax = plt.subplots(figsize=(12.8, 7.6), dpi=120)
    fig.subplots_adjust(top=0.78, bottom=0.1, left=0.08, right=0.97)
    _style_axes(fig, ax, x_max, y_min, y_max)

    _gradient_fill(ax, prof.distance_km.to_numpy(), prof.elevation_m.to_numpy(), y_min, _PENDING_CMAP, zorder=0)
    ax.plot(prof.distance_km, prof.elevation_m, color=BASELINE, linewidth=1.3, zorder=1)
    _legend(ax)

    reveal_fill_state = {"artist": ax.fill_between([], [], [], color="none")}
    (reveal_line,) = ax.plot([], [], color=CRITICAL, linewidth=2, zorder=1.5)
    (marker_glow,) = ax.plot([], [], marker="o", markersize=16, color=CRITICAL, alpha=0.18,
                              markeredgewidth=0, linestyle="", zorder=4)
    (marker,) = ax.plot([], [], marker="o", markersize=9, color=CRITICAL, markeredgecolor="white",
                         markeredgewidth=1.4, zorder=5, linestyle="")

    fig.text(0.08, 0.94, title, fontsize=19, fontweight="bold", color=INK_PRIMARY, ha="left", va="baseline")
    if subtitle:
        fig.text(0.08, 0.905, subtitle, fontsize=11, color=INK_SECONDARY, ha="left", va="baseline")
    clock_label = fig.text(0.97, 0.94, "", ha="right", va="baseline", fontsize=15, fontweight="bold", color=CRITICAL)
    clock_caption = fig.text(0.97, 0.918, "elapsed clock", ha="right", va="baseline", fontsize=9, color=INK_MUTED)

    stems, dots, name_labels, time_labels = [], [], [], []
    for _, row in cities.iterrows():
        (ln,) = ax.plot([row.distance_km] * 2, [row.elevation_m, row.elevation_m], color=GRIDLINE,
                         linewidth=1.3, zorder=2.5, solid_capstyle="round")
        dot = ax.scatter([row.distance_km], [row.elevation_m], s=46, color="white", edgecolor=INK_MUTED,
                          linewidth=1.3, zorder=4)
        name_t = ax.annotate(row["name"], xy=(row.distance_km, row.elevation_m), xytext=(6, 4),
                              textcoords="offset points", color=INK_MUTED, fontsize=9.6, va="bottom", ha="left", zorder=5)
        time_t = ax.annotate("", xy=(row.distance_km, row.elevation_m), xytext=(6, 17),
                              textcoords="offset points", color=INK_MUTED, fontsize=8, va="bottom", ha="left", zorder=5)
        stems.append(ln)
        dots.append(dot)
        name_labels.append(name_t)
        time_labels.append(time_t)

    def update(frame_x):
        mask = prof.distance_km <= frame_x
        xs = prof.distance_km[mask].to_numpy()
        ys = prof.elevation_m[mask].to_numpy()
        elev_here = float(np.interp(frame_x, profile.distance_km, profile.elevation_m))
        if len(xs) == 0 or xs[-1] < frame_x:
            xs = np.append(xs, frame_x)
            ys = np.append(ys, elev_here)

        reveal_fill_state["artist"].remove()
        reveal_fill_state["artist"] = ax.fill_between(xs, y_min, ys, color=ORANGE, alpha=0.30, zorder=1.1)
        reveal_line.set_data(xs, ys)
        marker.set_data([frame_x], [elev_here])
        marker_glow.set_data([frame_x], [elev_here])
        clock_label.set_text(Stopwatch.sec_to_hms(watch.time_at(frame_x)))

        for (_, row), h, ln, dot, name_t, time_t in zip(cities.iterrows(), shelf, stems, dots, name_labels, time_labels):
            reached = row.distance_km <= frame_x + 1e-6
            y1 = row.elevation_m + h + y_top_pad
            ln.set_data([row.distance_km] * 2, [row.elevation_m, y1])
            ln.set_color("#e7c3bd" if reached else GRIDLINE)
            dot.set_offsets([[row.distance_km, y1]])
            dot.set_facecolor(CRITICAL if reached else "white")
            dot.set_edgecolor("white" if reached else INK_MUTED)
            name_t.xy = (row.distance_km, y1)
            name_t.set_color(INK_PRIMARY if reached else INK_MUTED)
            name_t.set_fontweight("semibold" if reached else "normal")
            time_t.xy = (row.distance_km, y1)
            time_t.set_text(row.flood_time if (reached and isinstance(row.flood_time, str)) else "")
        return [reveal_line, marker, marker_glow, clock_label, *stems, *dots, *name_labels, *time_labels]

    anim = FuncAnimation(fig, update, frames=timeline, blit=False)
    out_gif.parent.mkdir(parents=True, exist_ok=True)
    anim.save(out_gif, writer=PillowWriter(fps=fps), savefig_kwargs={"facecolor": fig.get_facecolor()})

    if out_mp4 is not None:
        if shutil.which("ffmpeg"):
            from matplotlib.animation import FFMpegWriter

            anim.save(out_mp4, writer=FFMpegWriter(fps=fps, bitrate=4000), savefig_kwargs={"facecolor": fig.get_facecolor()})
        else:
            print(f"ffmpeg not found on PATH -- skipped MP4 export ({out_mp4} not written).")

    plt.close(fig)
