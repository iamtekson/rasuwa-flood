"""Zoomed-in damage maps (figure panels c-e), built into overviewmap.qgz by build_overview_layout.py.

One print layout, "Panels c-e": three maps side by side, each showing exactly one frame from
analysis/inputs/inset_frames.geojson (the boxes on panel a and the bands on panel b), on the best
post-event imagery available, with only the damaged features drawn. Under each map: its scale bar
and imagery credit; under all three: a shared legend.
Exports qgis_project/exports/panels_c_e.png (600 dpi) and .pdf.
"""
import csv
import math
from pathlib import Path

from qgis.core import (Qgis, QgsBilinearRasterResampler, QgsContrastEnhancement, QgsHueSaturationFilter, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsFillSymbol, QgsGeometry, QgsLayoutExporter, QgsLayoutItem, QgsMapRendererParallelJob, QgsMapSettings, QgsLayoutItemLabel,
                       QgsLayoutItemLegend, QgsLayoutItemMap, QgsLayoutItemPicture, QgsLayoutItemScaleBar,
                       QgsLayoutPoint, QgsLayoutSize, QgsLegendRenderer, QgsLegendStyle, QgsLineSymbol,
                       QgsCentroidFillSymbolLayer, QgsMarkerSymbol, QgsPrintLayout, QgsRasterLayer, QgsSimpleLineSymbolLayer,
                       QgsSingleSymbolRenderer)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor, QPainter

import build_overview_layout as ov

ROOT = Path(__file__).resolve().parents[2]
QP = ROOT / "qgis_project"
INTER = ROOT / "analysis" / "intermediate"
LAYOUT_NAME = "Panels c-e"
GROUP_NAME = "Panels c-e (layout layers)"
MM = Qgis.LayoutUnit.Millimeters

# ---- tunables ----
PAGE_W, GAP = 180, 2.5                       # mm; panel height follows from the frames' shapes
TITLE_H = 5.4                                # mm above each map for its letter and place name
FONT_PT = {"letter": 10, "title": 7.5, "town": 7.5, "km": 7, "hp": 6.8, "credit": 6, "scalebar": 6.5}
# Monochrome base, to match panel (a): imagery in greyscale, the hillshade multiplied over it at this
# opacity (0 = off). Set IMAGERY_GREYSCALE = False to keep the imagery in colour.
IMAGERY_GREYSCALE = False                    # True = greyscale imagery (monochrome figure)
IMAGERY_SATURATION = 20                      # colour imagery only: -100..100; offsets the wash-out of the gamma lift
# Sentinel-2 haze: its black point is set to S2_DEHAZE[1] x the S2_DEHAZE[0] % darkest value of each band,
# which removes the blue haze of top-of-atmosphere colour without crushing shadows to black. None = off.
S2_DEHAZE = (2.0, 0.7)
# Brightness. Forested slopes are very dark, and a plain stretch is set by the bright cloud tops, so each
# panel's imagery is stretched (STRETCH_CUT, %) and then lifted with the gamma that brings the rendered
# panel to IMAGERY_TARGET_LUMINANCE (0-255 mean grey; None = gamma 1). Same brightness in all three panels.
STRETCH_CUT = (0.0, 98.0)          # lower 0: cloud shadows stay dark grey instead of black
IMAGERY_TARGET_LUMINANCE = 150
IMAGERY_OPACITY = 1.0                        # below 1 fades the imagery towards white (e.g. 0.75)
# Relief: the hillshade blended over the imagery. "softlight" adds relief without darkening;
# "multiply" darkens. Opacity 0 = off.
HILLSHADE_OVERLAY_MODE = "softlight"
HILLSHADE_OVERLAY_OPACITY = 0.4
SCALE_BAR_FRACTION = 1 / 8                   # scale-bar segment length as a share of the map width (rounded 1-2-5)
SCALE_BAR_RAISE = {"d": 6.0}                 # mm to lift a panel's scale bar off labels near its lower-right corner
HP_LABEL_COLOR = "#ffc9c9"                   # hydropower names: italic, light red, so they read apart from towns
# Imagery per panel, drawn bottom to top. Panels not listed are automatic: the post-event Vantor clip
# if there is one, over 10 m post-event Sentinel-2. To use Planet for d, for example:
#   IMAGERY = {"d": [("qgis_project/imagery/planet/d_2026-09-10.tif", "PlanetScope, 10 Sep 2026")]}
IMAGERY = {"d": [("qgis_project/imagery/sentinel2/insets/d_S2_2026-09-21_2026-09-21.tif", "Sentinel-2, 21 Sep 2026")]}
TEXT_PAD = 1.5                               # mm between the page edge / map edge and titles and legend
LETTER_FMT = "({})"                          # panel letters (c)-(e)
SHOW_LEGEND = False                          # the combined figure has one shared key (compose_figure.py) instead
S2_INSET = "{panel}_S2_2026-08-27_2026-10-18.tif"
S2_CREDIT = "Sentinel-2 (Copernicus), post-event, Aug-Oct 2026"
SENSORS = {"WV03": "WorldView-3", "WV02": "WorldView-2", "GE01": "GeoEye-1", "LG06": "Legion-6"}
HP_LABELS = True                             # name hydropower structures (names from the layer)
KM_TICK_EVERY = 5                            # distance-from-source markers inside the maps
FLOOD_LINE = "#1f78d1"                       # flood inundation outline (darker than the lighter imagery)
BUILDING = "#ffd23f"                         # buildings in the flood inundation
ROAD = "#ff4fa3"                             # road in the flood inundation
# line widths (mm): (line, white casing underneath). Thin, so dense roads and footprints stay readable.
FLOOD_LINE_W = (0.18, 0.0)
ROAD_W = (0.22, 0.15)
HYDRO_W = (0.3, 0.2)
# What panels c-e draw. Roads off and hydropower as a marker keep the panels clean; the compose_figure.py
# key reads these too. HYDRO_STYLE: "marker" (red square at each structure, as in panels a and b),
# "outline" (the structure's footprint) or "off".
SHOW_ROADS = False
HYDRO_STYLE = "marker"
# marker sizes (mm), just above the 0.9 mm building dots; triangles look smaller than squares at one size
BUILDING_MM = 0.9
HYDRO_MARKER_MM = 1.4
BRIDGE_MARKER_MM = 1.6
DESTROYED, DAMAGED, INK, INK2, MUTED = ov.DESTROYED, ov.DAMAGED, ov.INK, ov.INK2, ov.MUTED


def white_text(size, bold=False, color="white", italic=False):
    """Light text with a dark halo, for labels on imagery."""
    fmt = ov.text_format(size, color, bold=bold, italic=italic, buffer=0.55)
    b = fmt.buffer()
    b.setColor(QColor(20, 20, 20))
    b.setOpacity(0.8)
    fmt.setBuffer(b)
    return fmt


def cased(symbol, color, width, casing):
    """Line (or polygon outline) with a white casing underneath, so it reads on any imagery."""
    symbol.deleteSymbolLayer(0)
    if casing:
        symbol.appendSymbolLayer(QgsSimpleLineSymbolLayer.create(
            {"line_color": "255,255,255,190", "line_width": str(width + casing), "capstyle": "round", "joinstyle": "round"}))
    symbol.appendSymbolLayer(QgsSimpleLineSymbolLayer.create(
        {"line_color": color, "line_width": str(width), "capstyle": "round", "joinstyle": "round"}))
    return symbol


def raster(path, name):
    lyr = QgsRasterLayer(str(path), name)
    if not lyr.isValid():
        raise SystemExit(f"could not load {path}")
    for band in range(1, lyr.bandCount() + 1):  # black collar outside a scene's footprint -> transparent
        lyr.dataProvider().setNoDataValue(band, 0)
    dehaze = S2_DEHAZE if (S2_DEHAZE and "_S2_" in Path(path).name) else None
    origin = lyr.renderer().minMaxOrigin()
    origin.setCumulativeCutLower((dehaze[0] if dehaze else STRETCH_CUT[0]) / 100)
    origin.setCumulativeCutUpper(STRETCH_CUT[1] / 100)
    lyr.setContrastEnhancement(QgsContrastEnhancement.StretchToMinimumMaximum, Qgis.RasterRangeLimit.CumulativeCut)
    r = lyr.renderer()
    for get in ("redContrastEnhancement", "greenContrastEnhancement", "blueContrastEnhancement"):
        ce = getattr(r, get, lambda: None)()
        if ce:  # black point at 0 (or just below the haze), so the darkest shadows keep a little value
            ce.setMinimumValue(ce.minimumValue() * dehaze[1] if dehaze else 0)
    r.setOpacity(IMAGERY_OPACITY)
    if IMAGERY_GREYSCALE:
        modes = getattr(QgsHueSaturationFilter, "GrayscaleMode", QgsHueSaturationFilter)
        lyr.hueSaturationFilter().setGrayscaleMode(modes.GrayscaleLuminosity)
    elif IMAGERY_SATURATION:
        lyr.hueSaturationFilter().setSaturation(IMAGERY_SATURATION)
    return lyr


def mean_luminance(layers, extent, crs, px=220):
    """Mean grey value (0-255) of the layers rendered over a white page."""
    ms = QgsMapSettings()
    ms.setDestinationCrs(crs)
    ms.setLayers(layers)
    ms.setExtent(extent)
    ms.setOutputSize(QSize(px, px))
    ms.setBackgroundColor(QColor("white"))
    job = QgsMapRendererParallelJob(ms)
    job.start()
    job.waitForFinished()
    img = job.renderedImage()
    vals = [QColor(img.pixel(x, y)) for y in range(0, px, 4) for x in range(0, px, 4)]
    return sum(0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue() for c in vals) / len(vals)


def calibrate_gamma(images, base, extent, crs, target):
    """Gamma (QGIS: above 1 brightens) for `images` so the rendered panel's mean grey is near `target`."""
    def render(g):
        for lyr in images:
            lyr.brightnessFilter().setGamma(g)
        return mean_luminance(base[:-1] + images[::-1] + base[-1:], extent, crs)
    lo, hi = 0.8, 6.0
    for _ in range(9):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if render(mid) < target else (lo, mid)
    g = (lo + hi) / 2
    return g, render(g)


def imagery_for(panel):
    """[(path, credit)] bottom to top."""
    if panel in IMAGERY:
        return [(ROOT / p, credit) for p, credit in IMAGERY[panel]]
    out = []
    s2 = QP / "imagery" / "sentinel2" / "insets" / S2_INSET.format(panel=panel)
    if s2.exists():
        out.append((s2, S2_CREDIT))
    for p in sorted((QP / "imagery" / "vantor").glob(f"{panel}_post_*.tif")):
        _, _, day, sensor, _ = p.stem.split("_")
        y, m, d = day.split("-")
        month = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()[int(m) - 1]
        out.append((p, f"Vantor {SENSORS.get(sensor, sensor)}, {int(d)} {month} {y}"))
    return out


def nice_step(km):
    """1-2-5 step close to km."""
    e = 10 ** math.floor(math.log10(km))
    return min((s * e for s in (1, 2, 5, 10)), key=lambda s: abs(s - km))


def add_label(layout, text, fmt, x, y, anchor=QgsLayoutItem.ReferencePoint.UpperLeft, background=False):
    lbl = QgsLayoutItemLabel(layout)
    lbl.setText(text)
    lbl.setTextFormat(fmt)
    lbl.setMargin(0.7 if background else 0)
    if background:
        lbl.setBackgroundEnabled(True)
        lbl.setBackgroundColor(QColor(255, 255, 255, 220))
    lbl.adjustSizeToText()
    lbl.setReferencePoint(anchor)
    lbl.attemptMove(QgsLayoutPoint(x, y, MM))
    layout.addLayoutItem(lbl)
    return lbl


def build(project):
    """Add the layout's layers (own styling, hidden group) and the 'Panels c-e' layout; return the layout."""
    for lay in [l for l in project.layoutManager().layouts() if l.name() == LAYOUT_NAME]:
        project.layoutManager().removeLayout(lay)
    tree = project.layerTreeRoot()
    old = tree.findGroup(GROUP_NAME)
    if old:
        for n in old.findLayers():
            project.removeMapLayer(n.layerId())
        tree.removeChildNode(old)

    # ---- vector layers styled for imagery ----
    flood = ov.vector(ROOT / "data/Impact-Assessment-Shashi-Ashim/Inundation/Inundation.shp", "Flood inundation")
    flood.setRenderer(QgsSingleSymbolRenderer(cased(QgsFillSymbol(), FLOOD_LINE, *FLOOD_LINE_W)))

    buildings = ov.vector(ROOT / "data/Impact-Assessment-Shashi-Ashim/Builidngs/Buildings.shp",
                          "Building in flood inundation")
    buildings.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": BUILDING, "outline_color": "#3a2f00", "outline_width": "0.12", "size": str(BUILDING_MM)})))

    roads = ov.vector(INTER / "roads_in_inundation.geojson", "Road in flood inundation")
    roads.setRenderer(QgsSingleSymbolRenderer(cased(QgsLineSymbol(), ROAD, *ROAD_W)))

    bridges = ov.vector(INTER / "bridges.geojson", "Bridges", subset="\"status\" IN ('Destroyed', 'Damaged')")
    tri = lambda col: QgsMarkerSymbol.createSimple(
        {"name": "triangle", "angle": "180", "color": col, "outline_color": "white", "outline_width": "0.15",
         "size": str(BRIDGE_MARKER_MM)})
    ov.rules(bridges, [("Bridge washed away", "\"status\" = 'Destroyed'", tri(DESTROYED)),
                       ("Bridge damaged", "\"status\" = 'Damaged'", tri(DAMAGED))])

    hydro = ov.vector(f"{INTER / 'hydropower.geojson'}|geometrytype=Polygon", "Hydropower structure damaged")
    if HYDRO_STYLE == "marker":  # a square at the centre of each footprint
        square = QgsMarkerSymbol.createSimple({"name": "square", "color": DESTROYED, "outline_color": "white",
                                               "outline_width": "0.15", "size": str(HYDRO_MARKER_MM)})
        centre = QgsCentroidFillSymbolLayer()
        centre.setSubSymbol(square)
        centre.setPointOnSurface(True)
        sym = QgsFillSymbol()
        sym.changeSymbolLayer(0, centre)
        hydro.setRenderer(QgsSingleSymbolRenderer(sym))
    else:
        hydro.setRenderer(QgsSingleSymbolRenderer(cased(QgsFillSymbol(), DESTROYED, *HYDRO_W)))
    if HP_LABELS:
        ov.label_layer(hydro, '"label"', white_text(FONT_PT["hp"], bold=True, color=HP_LABEL_COLOR, italic=True),
                       placement=Qgis.LabelPlacement.AroundPoint,
                       dist=1.0, priority=9)

    ticks = ov.vector(INTER / "flow_path" / "flow_path_km_ticks.shp", "Distance from source (km)",
                      subset=f'"km" > 0 AND "km" % {KM_TICK_EVERY} = 0')
    ticks.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": "white", "outline_color": INK, "outline_width": "0.3", "size": "1.8"})))
    ov.label_layer(ticks, "\"km\" || ' km'", white_text(FONT_PT["km"], bold=True), placement=Qgis.LabelPlacement.AroundPoint,
                   dist=0.8, priority=7)

    towns = ov.vector(ROOT / "data" / "cities.geojson", "Towns",
                      subset="\"name_en\" IS NOT NULL AND \"name_en\" NOT LIKE '%Old%'")
    towns.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": INK, "outline_color": "white", "outline_width": "0.25", "size": "1.3"})))  # as panel a
    ov.label_layer(towns, "regexp_replace(\"name_en\", '\\\\s*\\\\(.*\\\\)$', '')", white_text(FONT_PT["town"]),
                   placement=Qgis.LabelPlacement.AroundPoint, dist=0.8, priority=8)

    vectors = [ticks, towns] + ([hydro] if HYDRO_STYLE != "off" else []) + [bridges] \
        + ([roads] if SHOW_ROADS else []) + [buildings, flood]  # top to bottom
    hill = QgsRasterLayer(str(QP / "basemap" / "hillshade_multidirectional.tif"), "Hillshade")
    # the same hillshade again, multiplied over the imagery for relief and a consistent grey tone
    overlay = QgsRasterLayer(str(QP / "basemap" / "hillshade_multidirectional.tif"),
                             f"Hillshade overlay ({HILLSHADE_OVERLAY_MODE})")
    overlay.renderer().setOpacity(HILLSHADE_OVERLAY_OPACITY)
    overlay.setBlendMode({"softlight": QPainter.CompositionMode.CompositionMode_SoftLight,
                          "multiply": QPainter.CompositionMode.CompositionMode_Multiply,
                          "overlay": QPainter.CompositionMode.CompositionMode_Overlay}[HILLSHADE_OVERLAY_MODE])
    overlay.resampleFilter().setZoomedInResampler(QgsBilinearRasterResampler())  # 30 m cells, smooth at inset scale
    overlay.resampleFilter().setZoomedOutResampler(QgsBilinearRasterResampler())

    frames = ov.vector(ROOT / "analysis/inputs/inset_frames.geojson", "frames")
    bands = {r["panel"]: r for r in csv.DictReader(open(INTER / "inset_bands.csv", encoding="utf-8"))}
    utm = QgsCoordinateReferenceSystem("EPSG:32645")
    to_utm = QgsCoordinateTransform(frames.crs(), utm, project)
    panels = []
    for f in sorted(frames.getFeatures(), key=lambda f: f["panel"]):
        g = QgsGeometry(f.geometry())
        g.transform(to_utm)  # the frame itself, not its lat/long bounding box
        imgs = [(raster(p, f"{f['panel']}: {credit}"), credit)
                for p, credit in imagery_for(f["panel"])]
        panels.append({"panel": f["panel"], "place": f["place"], "bbox": g.boundingBox(), "imagery": imgs})

    if IMAGERY_TARGET_LUMINANCE:
        for p in panels:
            imgs = [l for l, _ in p["imagery"]]
            base = ([overlay] if HILLSHADE_OVERLAY_OPACITY > 0 else []) + [hill]
            g, lum = calibrate_gamma(imgs, base, p["bbox"], utm, IMAGERY_TARGET_LUMINANCE)
            print(f"panel {p['panel']}: imagery gamma {g:.2f} -> mean grey {lum:.0f}")

    group = tree.addGroup(GROUP_NAME)
    for lyr in vectors + [hill] + [l for p in panels for l, _ in p["imagery"]]:
        project.addMapLayer(lyr, False)
        group.addLayer(lyr)
    group.setItemVisibilityCheckedRecursive(False)

    # ---- layout: equal-height maps, widths from each frame's shape ----
    aspects = [p["bbox"].width() / p["bbox"].height() for p in panels]
    h = (PAGE_W - GAP * (len(panels) - 1)) / sum(aspects)
    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName(LAYOUT_NAME)
    project.layoutManager().addLayout(layout)
    x = 0.0
    maps, scale_bars = [], []
    for p, aspect in zip(panels, aspects):
        w = h * aspect
        m = QgsLayoutItemMap(layout)
        m.attemptMove(QgsLayoutPoint(x, TITLE_H, MM))
        m.attemptResize(QgsLayoutSize(w, h, MM))
        m.setCrs(utm)
        m.setExtent(p["bbox"])
        m.setLayers(vectors + ([overlay] if HILLSHADE_OVERLAY_OPACITY > 0 else [])
                    + [l for l, _ in reversed(p["imagery"])] + [hill])
        m.setKeepLayerSet(True)
        m.setFrameEnabled(True)
        m.setFrameStrokeWidth(ov.mm(0.25))
        m.setFrameStrokeColor(QColor(INK2))
        layout.addLayoutItem(m)
        maps.append(m)

        # title above the map, inset from the edge: bold panel letter, then "Place (from-to km)"
        b = bands.get(p["panel"])
        km = f" ({float(b['km_from']):.0f}–{float(b['km_to']):.0f} km)" if b else ""
        base = TITLE_H - 0.8
        letter = add_label(layout, LETTER_FMT.format(p["panel"]), ov.text_format(FONT_PT["letter"], INK, bold=True), x + TEXT_PAD, base,
                           anchor=QgsLayoutItem.ReferencePoint.LowerLeft)
        add_label(layout, p["place"].replace("-", "–") + km, ov.text_format(FONT_PT["title"], INK2),
                  x + TEXT_PAD + letter.rect().width() + 1.2, base - 0.15, anchor=QgsLayoutItem.ReferencePoint.LowerLeft)

        # imagery credit inside the map, lower right
        credit = p["imagery"][-1][1] if p["imagery"] else ""
        add_label(layout, credit, white_text(FONT_PT["credit"]), x + w - 0.8, TITLE_H + h - 0.6,
                  anchor=QgsLayoutItem.ReferencePoint.LowerRight)

        # scale bar inside the map, lower right just above the credit (the river leaves the frames at lower left);
        # placed after the layout's measuring pass below, once its true size is known
        sb = QgsLayoutItemScaleBar(layout)
        sb.setStyle("Single Box")
        sb.setLinkedMap(m)
        sb.applyDefaultSize(Qgis.DistanceUnit.Kilometers)
        sb.setUnits(Qgis.DistanceUnit.Kilometers)
        sb.setUnitLabel("km")
        sb.setUnitsPerSegment(nice_step(p["bbox"].width() / 1000 * SCALE_BAR_FRACTION))
        sb.setNumberOfSegments(2)
        sb.setNumberOfSegmentsLeft(0)
        sb.setHeight(0.8)
        sb.setLabelBarSpace(0.6)
        sb.setTextFormat(white_text(FONT_PT["scalebar"]))
        sb.setBoxContentSpace(0.3)
        sb.resizeToMinimumWidth()
        layout.addLayoutItem(sb)
        scale_bars.append((sb, x + w - 1.2, TITLE_H + h - 3.0 - SCALE_BAR_RAISE.get(p["panel"], 0)))
        x += w + GAP

    arrow = QgsLayoutItemPicture(layout)
    arrow.setPicturePath(":/images/north_arrows/layout_default_north_arrow.svg")
    arrow.setSvgFillColor(QColor("white"))
    arrow.setSvgStrokeColor(QColor(INK))
    arrow.setLinkedMap(maps[0])
    arrow.attemptResize(QgsLayoutSize(2.8, 4.8, MM))
    arrow.attemptMove(QgsLayoutPoint(maps[0].rect().width() - 4.0, TITLE_H + 1.0, MM))
    layout.addLayoutItem(arrow)

    legend = None
    if SHOW_LEGEND:
        legend = QgsLayoutItemLegend(layout)
        legend.setLinkedMap(maps[0])
        if hasattr(legend, "setSyncMode"):
            legend.setSyncMode(Qgis.LegendSyncMode.Manual)
        legend.setTitle("")
        root = legend.model().rootGroup()
        root.removeAllChildren()
        for lyr in [l for l in (flood, buildings, roads, hydro, bridges, ticks) if l in vectors]:
            node = root.addLayer(lyr)
            if lyr is bridges:
                QgsLegendRenderer.setNodeLegendStyle(node, QgsLegendStyle.Style.Hidden)
        for style in (QgsLegendStyle.Style.SymbolLabel, QgsLegendStyle.Style.Subgroup):
            legend.rstyle(style).setTextFormat(ov.text_format(7, INK2))
        legend.setColumnCount(4)
        legend.setSplitLayer(True)
        legend.setSymbolWidth(4.0)
        legend.setSymbolHeight(2.4)
        legend.setColumnSpace(5.0)
        legend.setBoxSpace(0)
        legend.setBackgroundEnabled(False)
        legend.setFrameEnabled(False)
        legend.setResizeToContents(True)
        layout.addLayoutItem(legend)
        legend.attemptMove(QgsLayoutPoint(TEXT_PAD, TITLE_H + h + 1.5, MM))
    # QGIS only measures legends and scale bars when it draws them: render once at low resolution, then size
    layout.pageCollection().page(0).setPageSize(QgsLayoutSize(PAGE_W, TITLE_H + h + 40, MM))
    QgsLayoutExporter(layout).renderPageToImage(0, QSize(), 40)
    for sb, right, bottom in scale_bars:  # drop the default size's empty space, then pin the lower-right corner
        sb.attemptResize(sb.minimumSize())
        sb.setReferencePoint(QgsLayoutItem.ReferencePoint.LowerRight)
        sb.attemptMove(QgsLayoutPoint(right, bottom, MM))
    page_h = TITLE_H + h + 0.3
    if legend:
        legend.adjustBoxSize()
        page_h += 1.2 + legend.sizeWithUnits().height() + 0.5
    layout.pageCollection().page(0).setPageSize(QgsLayoutSize(PAGE_W, page_h, MM))
    return layout


def export(layout, out):
    exporter = QgsLayoutExporter(layout)
    img = QgsLayoutExporter.ImageExportSettings()
    img.dpi = 600
    pdf = QgsLayoutExporter.PdfExportSettings()
    r1 = exporter.exportToImage(str(out / "panels_c_e.png"), img)
    r2 = exporter.exportToPdf(str(out / "panels_c_e.pdf"), pdf)
    print("panels c-e export png:", r1, "| pdf:", r2)
