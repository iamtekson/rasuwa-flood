# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow", "pypdf", "matplotlib>=3.8"]
# ///
"""Stack panels a, b and c-e into the single damage figure (180 mm wide), with one shared key.

    uv run analysis/scripts/compose_figure.py

Run after the panels are exported:
  b       uv run analysis/scripts/damage_profile.py              -> analysis/outputs/damage_profile.*
  a, c-e  QGIS: qgis_project/scripts/build_overview_layout.py    -> qgis_project/exports/overview_map.*, panels_c_e.*
Writes analysis/outputs/damage_figure.png (600 dpi) and damage_figure.pdf (the panels' own PDFs placed on
one page, so text and lines stay vector).

The key replaces the per-panel legends: one row per feature, one column per panel showing how that
feature is drawn there. It is drawn in the free area under panel a's locator (position written by
build_overview_layout.py) and takes its colours from the panel scripts, so it always matches them.
Dotted rules separate the rows a | b | c-e.
"""
import ast
import json
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from PIL import Image
from pypdf import PageObject, PdfReader, PdfWriter, Transformation

ROOT = Path(__file__).resolve().parents[2]
PANELS = [ROOT / "qgis_project" / "exports" / "overview_map",   # a
          ROOT / "analysis" / "outputs" / "damage_profile",     # b
          ROOT / "qgis_project" / "exports" / "panels_c_e"]     # c-e
LAYOUT_A = ROOT / "qgis_project" / "exports" / "overview_map_layout.json"
OUT = ROOT / "analysis" / "outputs" / "damage_figure"
DPI = 600
MM_PT = 72 / 25.4

# ---- tunables ----
GAP_MM = 5.0                                         # space between the rows a | b | c-e
SEPARATOR = dict(color="#a9a69d", linewidth=0.6, linestyle=(0, (1, 2.5)))  # dotted rule in each gap
KEY_FONT_PT, KEY_HEADER_PT = 6.0, 6.5
KEY_COLUMNS_MM = (3.0, 9.0, 15.5)                    # symbol-column centres for (a), (b), (c-e)
KEY_LABEL_X_MM = 20.0                                # where the row labels start

Image.MAX_IMAGE_PIXELS = None


def constants(path):
    """Top-level literal constants of a script (colours, widths), read without importing it."""
    out = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if not isinstance(node, ast.Assign):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            continue
        for t in node.targets:
            if isinstance(t, ast.Name):
                out[t.id] = value
            elif isinstance(t, ast.Tuple) and isinstance(value, tuple) and len(t.elts) == len(value):
                out.update({e.id: v for e, v in zip(t.elts, value) if isinstance(e, ast.Name)})
    return out


def style():
    a = constants(ROOT / "qgis_project" / "scripts" / "build_overview_layout.py")
    ce = constants(ROOT / "qgis_project" / "scripts" / "inset_layout.py")
    b = constants(ROOT / "analysis" / "scripts" / "damage_profile.py")
    return {"a": a, "ce": ce, "b": b}


def bridge_counts():
    feats = json.loads((ROOT / "analysis" / "intermediate" / "bridges.geojson").read_text(encoding="utf-8"))["features"]
    return Counter(f["properties"]["status"] for f in feats)


def draw_key(ax, x0, y0, w, h, S, counts):
    """The shared key, drawn in mm with y pointing down, inside the box (x0, y0, w, h)."""
    A, B, CE = S["a"], S["b"], S["ce"]
    ink, ink2 = A["INK"], A["INK2"]
    red, orange = A["DESTROYED"], A["DAMAGED"]
    st = B["STATUS"]
    ca, cb, cce = (x0 + c for c in KEY_COLUMNS_MM)

    def rect(cx, cy, w_, h_, **kw):
        ax.add_patch(Rectangle((cx - w_ / 2, cy - h_ / 2), w_, h_, **kw))

    def mark(cx, cy, marker, size, face, edge="white", ew=0.5):
        ax.add_line(Line2D([cx], [cy], marker=marker, markersize=size, markerfacecolor=face,
                           markeredgecolor=edge, markeredgewidth=ew, linestyle=""))

    def line(cx, cy, color, lw_mm, casing_mm=0.0, dashes=None, length=4.2):
        xs = [cx - length / 2, cx + length / 2]
        if casing_mm:
            ax.add_line(Line2D(xs, [cy, cy], color="white", linewidth=(lw_mm + casing_mm) * MM_PT, solid_capstyle="round"))
        kw = {"dashes": [float(v) * MM_PT for v in dashes.split(";")]} if dashes else {"solid_capstyle": "round"}
        ax.add_line(Line2D(xs, [cy, cy], color=color, linewidth=lw_mm * MM_PT, **kw))

    def outline(cx, cy, color, lw_mm, casing_mm=0.0):
        if casing_mm:
            rect(cx, cy, 3.6, 2.2, fill=False, edgecolor="white", linewidth=(lw_mm + casing_mm) * MM_PT)
        rect(cx, cy, 3.6, 2.2, fill=False, edgecolor=color, linewidth=lw_mm * MM_PT)

    band_rgb = tuple(int(A["BAND"][i:i + 2], 16) / 255 for i in (1, 3, 5))
    rows = [  # (label, symbol in (a), in (b), in (c-e)); None = not drawn in that panel
        ("Flood inundation",
         lambda x, y: rect(x, y, 3.6, 2.2, facecolor=A["FLOOD"], edgecolor=A["FLOOD"], linewidth=0.35 * MM_PT),
         None,
         lambda x, y: outline(x, y, CE["FLOOD_LINE"], 0.4)),
        ("Flood source", lambda x, y: mark(x, y, "*", 7.5, "#ffd23f", ink, 0.5), None, None),
        ("Distance from source (km)",
         lambda x, y: mark(x, y, "o", 4.2, "white", ink, 0.6),
         lambda x, y: ax.text(x, y, "x-axis", ha="center", va="center", fontsize=4.6, color=A["MUTED"]),
         lambda x, y: mark(x, y, "o", 4.8, "white", ink, 0.7)),
        ("Town",
         lambda x, y: mark(x, y, "o", 3.6, ink, "white", 0.4),
         None,
         lambda x, y: mark(x, y, "o", 3.6, ink, "white", 0.4)),
        None,  # group gap
        ("Building in flood inundation",
         None,
         lambda x, y: rect(x, y, 3.0, 2.3, facecolor=B["MAIN"], edgecolor="none"),
         lambda x, y: mark(x, y, "o", 2.8, CE["BUILDING"], "#3a2f00", 0.35)),
        ("Road in flood inundation",
         None,
         lambda x, y: (rect(x, y + 0.6, 3.0, 1.1, facecolor=B["MAIN"], edgecolor="white", linewidth=0.4),
                       rect(x, y - 0.6, 3.0, 1.1, facecolor=B["LOCAL"], edgecolor="white", linewidth=0.4)),
         lambda x, y: line(x, y, CE["ROAD"], 0.35, 0.3)),
        ("Hydropower structure damaged",
         lambda x, y: mark(x, y, "s", 5.2, red),
         lambda x, y: mark(x, y, "s", 5.2, red),
         lambda x, y: outline(x, y, red, 0.45, 0.3)),
        (f"Bridge washed away ({counts.get('Destroyed', 0)})",
         lambda x, y: mark(x, y, "v", 5.0, red), lambda x, y: mark(x, y, "v", 5.0, st["Destroyed"]),
         lambda x, y: mark(x, y, "v", 6.4, red, "white", 0.6)),
        (f"Bridge damaged ({counts.get('Damaged', 0)})",
         lambda x, y: mark(x, y, "v", 5.0, orange), lambda x, y: mark(x, y, "v", 5.0, st["Damaged"]),
         lambda x, y: mark(x, y, "v", 6.4, orange, "white", 0.6)),
        (f"Bridge intact ({counts.get('Intact', 0)})",
         None, lambda x, y: mark(x, y, "v", 5.0, "white", st["Intact"], 0.6), None),
        (f"Bridge, no information ({counts.get('No info', 0)})",
         None, lambda x, y: mark(x, y, "o", 3.0, "white", st["Intact"], 0.6), None),
        None,
        ("Zoomed areas (c)–(e)",
         lambda x, y: rect(x, y, 3.6, 2.4, facecolor=(*band_rgb, 110 / 255), edgecolor=A["BAND_EDGE"],
                           linewidth=0.4 * MM_PT),
         lambda x, y: rect(x, y, 2.4, 3.0, facecolor=B["BAND"], edgecolor="none"),
         None),
        ("District boundary",
         lambda x, y: line(x, y, A["BOUNDARY_COLOR"], A["BOUNDARY_WIDTH"], dashes=A["BOUNDARY_DASH"], length=4.8),
         None, None),
    ]
    header_h, group_gap = 4.2, 1.2
    n_rows = sum(r is not None for r in rows)
    pitch = (h - header_h - group_gap * rows.count(None)) / n_rows

    for cx, text in zip((ca, cb, cce), ("(a)", "(b)", "(c–e)")):
        ax.text(cx, y0 + 1.6, text, ha="center", va="center", fontsize=KEY_HEADER_PT, fontweight="bold", color=ink)
    ax.text(x0 + KEY_LABEL_X_MM, y0 + 1.6, "Symbol in panel", ha="left", va="center", fontsize=KEY_FONT_PT - 0.4,
            color=A["MUTED"], style="italic")
    ax.add_line(Line2D([x0, x0 + w], [y0 + 3.4, y0 + 3.4], color="#d6d4cc", linewidth=0.4))

    y = y0 + header_h + pitch / 2
    for row in rows:
        if row is None:
            y += group_gap
            continue
        label, sa, sb, sce = row
        for cx, sym in ((ca, sa), (cb, sb), (cce, sce)):
            if sym:
                sym(cx, y)
            else:
                ax.add_line(Line2D([cx - 0.5, cx + 0.5], [y, y], color="#d6d4cc", linewidth=0.5))  # not in panel
        ax.text(x0 + KEY_LABEL_X_MM, y, label, ha="left", va="center", fontsize=KEY_FONT_PT, color=ink2)
        y += pitch


def overlay(width_mm, height_mm, separators_mm, key_box_mm, S, counts, path, transparent_png=False):
    """One page the size of the figure holding the key and the separators, drawn in mm."""
    fig = plt.figure(figsize=(width_mm / 25.4, height_mm / 25.4))
    fig.patch.set_alpha(0)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, width_mm)
    ax.set_ylim(height_mm, 0)
    ax.set_axis_off()
    ax.patch.set_alpha(0)
    for y in separators_mm:
        ax.add_line(Line2D([0, width_mm], [y, y], **SEPARATOR))
    draw_key(ax, *key_box_mm, S, counts)
    fig.savefig(path, dpi=DPI, transparent=True)
    plt.close(fig)


def main():
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Arial", "Segoe UI", "DejaVu Sans"],
                         "lines.scale_dashes": False, "pdf.fonttype": 42})
    S, counts = style(), bridge_counts()
    key_box = json.loads(LAYOUT_A.read_text(encoding="utf-8"))["key_box_mm"]  # panel a sits at the top, at (0, 0)

    # PNG: panels on a white canvas, the overlay alpha-composited on top
    imgs = [Image.open(p.with_suffix(".png")).convert("RGBA") for p in PANELS]
    width = max(i.width for i in imgs)
    if any(abs(i.width - width) > 2 for i in imgs):
        raise SystemExit(f"panel widths differ: {[i.width for i in imgs]} px; all panels must be 180 mm")
    gap = round(GAP_MM / 25.4 * DPI)
    canvas = Image.new("RGBA", (width, sum(i.height for i in imgs) + gap * (len(imgs) - 1)), "white")
    y, seps = 0, []
    for k, img in enumerate(imgs):
        canvas.paste(img, (0, y))
        y += img.height
        if k < len(imgs) - 1:
            seps.append((y + gap / 2) * 25.4 / DPI)
            y += gap
    png_overlay = OUT.parent / "_overlay.png"
    overlay(canvas.width * 25.4 / DPI, canvas.height * 25.4 / DPI, seps, key_box, S, counts, png_overlay)
    canvas = Image.alpha_composite(canvas, Image.open(png_overlay).convert("RGBA").resize(canvas.size))
    canvas.convert("RGB").save(OUT.with_suffix(".png"), dpi=(DPI, DPI))

    # PDF: the panels' own vector pages stacked on one sheet, the overlay page merged on top
    pages = [PdfReader(p.with_suffix(".pdf")).pages[0] for p in PANELS]
    gap_pt = GAP_MM * MM_PT
    w_pt = max(float(p.mediabox.width) for p in pages)
    h_pt = sum(float(p.mediabox.height) for p in pages) + gap_pt * (len(pages) - 1)
    sheet = PageObject.create_blank_page(width=w_pt, height=h_pt)
    top, seps = h_pt, []
    for k, page in enumerate(pages):  # PDF origin is bottom-left: place each panel below the previous one
        top -= float(page.mediabox.height)
        sheet.merge_transformed_page(page, Transformation().translate(-float(page.mediabox.left),
                                                                      top - float(page.mediabox.bottom)))
        if k < len(pages) - 1:
            seps.append((h_pt - top + gap_pt / 2) / MM_PT)
            top -= gap_pt
    pdf_overlay = OUT.parent / "_overlay.pdf"
    overlay(w_pt / MM_PT, h_pt / MM_PT, seps, key_box, S, counts, pdf_overlay)
    sheet.merge_page(PdfReader(pdf_overlay).pages[0])
    writer = PdfWriter()
    writer.add_page(sheet)
    with open(OUT.with_suffix(".pdf"), "wb") as f:
        writer.write(f)
    png_overlay.unlink()
    pdf_overlay.unlink()
    print(f"damage_figure.png: {canvas.width} x {canvas.height} px | damage_figure.pdf: "
          f"{w_pt / MM_PT:.0f} x {h_pt / MM_PT:.0f} mm -> {OUT.parent}")


if __name__ == "__main__":
    main()
