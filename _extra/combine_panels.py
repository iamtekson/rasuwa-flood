"""Combine figures into one image, labelled (A), (B), ... at the top-left of each panel.

Usage:
    python combine_panels.py                          # the two braiding-index figures in Downloads
    python combine_panels.py a.png b.png -o out.png   # any figures, in panel order

Panels are scaled to a common width (vertical layout) or height (horizontal layout) and each gets a
white strip above it holding its label, so the label never sits on top of the plot.
"""
import argparse
import string
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DOWNLOADS = Path.home() / "Downloads"
DEFAULT_INPUTS = [DOWNLOADS / "bi_distance_hexbin_year_v4.png",
                  DOWNLOADS / "braiding_index_by_section.png"]
DEFAULT_OUTPUT = DOWNLOADS / "braiding_index_combined.png"

# ---- styling knobs -------------------------------------------------------------------------------
LAYOUT = "vertical"           # "vertical" = A above B; "horizontal" = A left of B
MATCH = "min"                 # scale panels to the "min" (no upsampling) or "max" common width/height
OUTPUT_DPI = 300              # written to the PNG; also converts the pt sizes below to pixels
LABEL_FMT = "({})"            # "({})" -> (A); "{}" -> A; "{})" -> A)
LABEL_FONTS = ["DejaVuSans-Bold.ttf", "arialbd.ttf"]  # first one found wins (matplotlib's font first)
LABEL_SIZE_PT = 20
LABEL_OFFSET_PT = (4, 6)      # (x, y) from the panel's top-left corner to the label's top-left ink
LABEL_STRIP = True            # add a white strip above each panel for its label; False = draw on the figure
GAP_PT = 16                   # white space between panels (the separator sits in the middle of it)
MARGIN_PT = 4                 # white border around the whole figure
SEPARATOR = True              # dashed line between panels
SEPARATOR_COLOR = "#808080"
SEPARATOR_WIDTH_PT = 1
SEPARATOR_DASH_PT = (6, 4)    # (dash length, space length)
BACKGROUND = "white"
# --------------------------------------------------------------------------------------------------


def pt(points):
    return round(points * OUTPUT_DPI / 72)


def load_font():
    for name in LABEL_FONTS:
        try:
            return ImageFont.truetype(name, pt(LABEL_SIZE_PT))
        except OSError:
            continue
    raise OSError(f"none of the label fonts could be loaded: {LABEL_FONTS}")


def flatten(path):
    """Open an image and composite any transparency onto the background colour."""
    im = Image.open(path)
    im = im.convert("RGBA")
    bg = Image.new("RGBA", im.size, BACKGROUND)
    return Image.alpha_composite(bg, im).convert("RGB")


def scale_to_common_size(panels):
    pick = min if MATCH == "min" else max
    if LAYOUT == "vertical":
        width = pick(p.width for p in panels)
        return [p.resize((width, round(p.height * width / p.width)), Image.LANCZOS) for p in panels]
    height = pick(p.height for p in panels)
    return [p.resize((round(p.width * height / p.height), height), Image.LANCZOS) for p in panels]


def add_label(panel, text, font):
    """Return the panel with its label at the top-left, on a strip above it if LABEL_STRIP."""
    ox, oy = pt(LABEL_OFFSET_PT[0]), pt(LABEL_OFFSET_PT[1])
    left, top, right, bottom = font.getbbox(text)
    strip = (bottom - top) + 2 * oy if LABEL_STRIP else 0
    out = Image.new("RGB", (panel.width, panel.height + strip), BACKGROUND)
    out.paste(panel, (0, strip))
    # shift by the ink bbox so the visible glyphs (not the font's line box) start at the offset
    ImageDraw.Draw(out).text((ox - left, oy - top), text, font=font, fill="black")
    return out


def draw_dashed(draw, start, end):
    """Dashed horizontal or vertical line from start to end."""
    (x0, y0), (x1, y1) = start, end
    dash, space = pt(SEPARATOR_DASH_PT[0]), pt(SEPARATOR_DASH_PT[1])
    length = abs(x1 - x0) + abs(y1 - y0)
    dx, dy = (x1 - x0) / length, (y1 - y0) / length
    for s in range(0, length, dash + space):
        e = min(s + dash, length)
        draw.line([(x0 + dx * s, y0 + dy * s), (x0 + dx * e, y0 + dy * e)],
                  fill=SEPARATOR_COLOR, width=pt(SEPARATOR_WIDTH_PT))


def combine(paths, output):
    font = load_font()
    panels = scale_to_common_size([flatten(p) for p in paths])
    panels = [add_label(p, LABEL_FMT.format(letter), font)
              for p, letter in zip(panels, string.ascii_uppercase)]

    gap, margin = pt(GAP_PT), pt(MARGIN_PT)
    if LAYOUT == "vertical":
        size = (max(p.width for p in panels),
                sum(p.height for p in panels) + gap * (len(panels) - 1))
    else:
        size = (sum(p.width for p in panels) + gap * (len(panels) - 1),
                max(p.height for p in panels))
    canvas = Image.new("RGB", (size[0] + 2 * margin, size[1] + 2 * margin), BACKGROUND)

    draw = ImageDraw.Draw(canvas)
    x = y = margin
    for i, p in enumerate(panels):
        canvas.paste(p, (x, y))
        separate = SEPARATOR and i < len(panels) - 1
        if LAYOUT == "vertical":
            y += p.height + gap
            if separate:
                draw_dashed(draw, (margin, y - gap // 2), (canvas.width - margin, y - gap // 2))
        else:
            x += p.width + gap
            if separate:
                draw_dashed(draw, (x - gap // 2, margin), (x - gap // 2, canvas.height - margin))

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, dpi=(OUTPUT_DPI, OUTPUT_DPI))
    print(f"wrote {output} ({canvas.width} x {canvas.height} px, "
          f"{canvas.width / OUTPUT_DPI:.2f} x {canvas.height / OUTPUT_DPI:.2f} in at {OUTPUT_DPI} dpi)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("images", nargs="*", type=Path, help="figures in panel order (A, B, ...)")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    combine(args.images or DEFAULT_INPUTS, args.output)
