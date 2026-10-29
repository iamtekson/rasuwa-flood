"""Build the overview map (figure panel a) in qgis_project/overviewmap.qgz and export it.

Run with QGIS's Python (after analysis/scripts/build_intermediate.py and build_basemap.py):
    "C:\\Program Files\\QGIS 4.0.2\\bin\\python-qgis.bat" qgis_project\\scripts\\build_overview_layout.py

What it does:
  - backs up the current project to qgis_project/archive/
  - restyles / adds the layers and sorts them into groups (overview, imagery, inset layers, locator)
  - creates the print layout "Panel a - overview" (180 x 83 mm): the flood corridor, rotated so the river
    runs left-right and clipped to CORRIDOR_BUFFER_KM either side of the flow path; scale bar, north
    arrow (rotates with the map), Nepal locator, and an empty box where compose_figure.py draws the key
  - exports qgis_project/exports/overview_map.png (600 dpi) and .pdf
Colours match the damage profile (panel b). Re-running rebuilds the layout from scratch.
"""
import json
import math
import shutil
from datetime import date
from pathlib import Path

from qgis.core import (Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature, QgsGeometry, QgsLayoutItem,
                       QgsPointXY, QgsFillSymbol, QgsLayerTreeGroup,
                       QgsLayerTreeLayer, QgsLayoutExporter, QgsLayoutItemLabel, QgsLayoutItemLegend, QgsLayoutItemMap,
                       QgsLayoutItemMapGrid, QgsLayoutItemMapOverview, QgsLayoutItemPicture, QgsLayoutItemScaleBar,
                       QgsLayoutMeasurement, QgsLayoutPoint, QgsLayoutSize, QgsLegendStyle, QgsLineSymbol,
                       QgsMarkerSymbol, QgsPalLayerSettings, QgsPrintLayout, QgsSimpleLineSymbolLayer, QgsProject, QgsProperty, QgsRasterLayer,
                       QgsRectangle, QgsRuleBasedRenderer, QgsSingleSymbolRenderer, QgsTextBufferSettings,
                       QgsTextFormat, QgsVectorLayer, QgsVectorLayerSimpleLabeling, QgsLegendRenderer)
from osgeo import gdal
from qgis.PyQt.QtGui import QColor, QFont

ROOT = Path(__file__).resolve().parents[2]
QP = ROOT / "qgis_project"
PROJECT = QP / "overviewmap.qgz"
INTER = ROOT / "analysis" / "intermediate"
LAYOUT_NAME = "Panel a - overview"

# Page and item positions (mm from the page's top-left). The map fills the page; the corridor is rotated
# MAP_ROTATION degrees clockwise and scaled to the page width, and the free white space around it holds
# the scale bar, the key (drawn later by compose_figure.py) and the locator.
PAGE = (180, 78)
MAP_ROTATION = 28                    # degrees clockwise; 28 lays the source-to-Mugling corridor flattest
CORRIDOR_MARGIN = (1.0, 0.5)         # mm left/right of the corridor, and below it
LETTER_POS = (1.0, 1.0)              # (a)
SCALEBAR_POS = (1.5, 68.0)           # upper-left corner of the scale bar: bottom left, below the 160-140 km reach
SCALEBAR_KM = 5                      # km per scale-bar segment (two segments)
NORTH_POS = (25.0, 68.5)             # upper-left corner of the north arrow, right of the scale bar
KEY_BOX = (44.0, 0.5, 56.0, 44.0)    # x, y, w, h: where compose_figure.py draws the shared key (top, in the dip)
LOCATOR_BOX = (138.0, 51.0, 41.0, 19.5)  # bottom right, below the 40 km reach
CREDIT_POS = (138.0, 71.2)           # under the locator
LETTER_FMT = "({})"                  # panel letter (a) and inset references (c)-(e)
SHOW_LEGEND = False                  # the combined figure has one shared key (compose_figure.py) instead
LOCATOR_LABELS = [("CHINA", 85.0, 30.3), ("NEPAL", 82.3, 28.75), ("INDIA", 82.6, 26.75)]
# Which vertex of each (north-up) inset frame its letter sits by, and on which side of that vertex.
LETTER_SPOT = {"c": ("top-left", "AboveLeft"), "d": ("top-left", "AboveLeft"), "e": ("top-left", "AboveLeft")}
# Towns named on the map (names as in analysis/intermediate/towns.csv).
TOWNS = ["Rasuwagadhi", "Syafrubesi", "Betrawati", "Bidur", "Galchi", "Malekhu", "Chumlingtar"]
FONT_PT = {"letter": 10, "frame_letter": 9.5, "town": 7.5, "km": 7, "district": 7, "country": 7.5,
           "scalebar": 7, "locator": 6.5, "credit": 6}

# Neutral greys, to match the manuscript's other distance figures (Kristen Cook's profile figure).
INK, INK2, MUTED = "#0b0b0b", "#4d4d4d", "#808080"
FLOOD = "#2b7bb9"
DESTROYED, DAMAGED = "#d03b3b", "#ec835a"
BAND, BAND_EDGE = "#D8D9D8", "#6e6450"  # zoom areas: warm, so they stand out on the grey hillshade
HILLSHADE_OPACITY = 0.55
DISTRICT = "#4d4d4d"  # district names
# District boundary line: colour, width (mm) and dash pattern (dash;gap;dot;gap, mm); the white edging under it
# keeps it readable on dark slopes (last value = opacity 0-255).
BOUNDARY_COLOR, BOUNDARY_WIDTH, BOUNDARY_DASH = "#8c8c8c", 0.3, "2.4;0.9;0.5;0.9"
BOUNDARY_EDGING = "255,255,255,60"
FONT = "Arial"


def mm(v):
    return QgsLayoutMeasurement(v, Qgis.LayoutUnit.Millimeters)


def text_format(size, color=INK2, bold=False, italic=False, buffer=0.0, spacing=0.0):
    f = QFont(FONT)
    f.setBold(bold)
    f.setItalic(italic)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    fmt = QgsTextFormat()
    fmt.setFont(f)
    fmt.setSize(size)
    fmt.setSizeUnit(Qgis.RenderUnit.Points)
    fmt.setColor(QColor(color))
    if buffer:
        b = QgsTextBufferSettings()
        b.setEnabled(True)
        b.setSize(buffer)
        b.setSizeUnit(Qgis.RenderUnit.Millimeters)
        b.setColor(QColor("white"))
        b.setOpacity(0.85)
        fmt.setBuffer(b)
    return fmt


def label_layer(layer, expression, fmt, placement=None, dist=0.8, priority=5, extra=None):
    s = QgsPalLayerSettings()
    s.fieldName = expression
    s.isExpression = True
    s.setFormat(fmt)
    if placement is not None:
        s.placement = placement
    s.dist = dist
    s.priority = priority
    for prop, expr in (extra or {}).items():
        s.dataDefinedProperties().setProperty(prop, QgsProperty.fromExpression(expr))
    layer.setLabeling(QgsVectorLayerSimpleLabeling(s))
    layer.setLabelsEnabled(True)


def vector(path, name, subset=None):
    lyr = QgsVectorLayer(str(path), name, "ogr")
    if not lyr.isValid():
        raise SystemExit(f"could not load {path}")
    if subset:
        lyr.setSubsetString(subset)
    return lyr


def rules(layer, items):
    root = QgsRuleBasedRenderer.Rule(None)
    for label, expr, sym in items:
        root.appendChild(QgsRuleBasedRenderer.Rule(sym, filterExp=expr, label=label))
    layer.setRenderer(QgsRuleBasedRenderer(root))


def main():
    app = QgsApplication([], False)
    app.initQgis()
    (QP / "archive").mkdir(exist_ok=True)
    backup = QP / "archive" / f"overviewmap_before_layout_{date.today()}.qgz"
    if not backup.exists():
        shutil.copy2(PROJECT, backup)

    project = QgsProject.instance()
    project.read(str(PROJECT))
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:32645"))
    by_name = {l.name(): l for l in project.mapLayers().values()}

    # keep the user's Sentinel Hub WMS layers and the inset road layers; rebuild everything else
    keep_wms = [l for l in by_name.values() if l.providerType() == "wms"]
    keep_roads = [by_name[n] for n in ("roads_in_inundation", "roads_near_inundation") if n in by_name]
    for l in list(by_name.values()):
        if l not in keep_wms + keep_roads:
            project.removeMapLayer(l.id())
    project.layoutManager().clear()
    tree = project.layerTreeRoot()

    # ---------------- overview layers ----------------
    utm = QgsCoordinateReferenceSystem("EPSG:32645")
    corridor_path = INTER / "map_a" / "corridor.geojson"
    corridor_layer = vector(corridor_path, "Corridor")
    corridor = next(corridor_layer.getFeatures()).geometry()
    corridor.transform(QgsCoordinateTransform(corridor_layer.crs(), utm, project))

    # hillshade cut to the corridor; outside it the page stays white
    hill_src = QP / "basemap" / "hillshade_multidirectional.tif"
    hill_clip = QP / "basemap" / "hillshade_corridor.tif"
    gdal.UseExceptions()
    gdal.Warp(str(hill_clip), str(hill_src), cutlineDSName=str(corridor_path), cropToCutline=True, dstAlpha=True,
              creationOptions=["COMPRESS=DEFLATE", "TILED=YES"])
    hill = QgsRasterLayer(str(hill_clip), "Hillshade (Copernicus DEM GLO-30), corridor")
    hill.renderer().setOpacity(HILLSHADE_OPACITY)

    districts = vector(INTER / "map_a" / "district_boundaries.geojson", "District boundaries")
    # dash-dot boundary on a faint white casing, so it reads on light and dark hillshade alike
    boundary = QgsLineSymbol()
    boundary.deleteSymbolLayer(0)
    boundary.appendSymbolLayer(QgsSimpleLineSymbolLayer.create(
        {"line_color": BOUNDARY_EDGING, "line_width": "0.9", "capstyle": "round", "joinstyle": "round"}))
    boundary.appendSymbolLayer(QgsSimpleLineSymbolLayer.create(
        {"line_color": BOUNDARY_COLOR, "line_width": str(BOUNDARY_WIDTH), "use_custom_dash": "1", "customdash": BOUNDARY_DASH,
         "customdash_unit": "MM", "capstyle": "flat", "joinstyle": "round"}))
    districts.setRenderer(QgsSingleSymbolRenderer(boundary))

    names = {}  # district and country names: label-only point layers, placed by build_intermediate.py
    for kind, fmt in [("district", text_format(FONT_PT["district"], DISTRICT, bold=True, spacing=1.0, buffer=0.8)),
                      ("country", text_format(FONT_PT["country"], "#5c5c5c", bold=True, spacing=1.4, buffer=0.7))]:
        lyr = vector(INTER / "map_a" / "label_points.geojson", f"{kind.title()} names", subset=f"\"kind\" = '{kind}'")
        lyr.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({"name": "circle", "size": "0",
                                                                              "color": "0,0,0,0", "outline_style": "no"})))
        label_layer(lyr, '"text"', fmt, placement=Qgis.LabelPlacement.OverPoint, priority=10 if kind == "country" else 2)
        if kind == "country":  # the border reach is crowded; never drop CHINA / NEPAL
            settings = lyr.labeling().settings()
            settings.displayAll = True
            lyr.setLabeling(QgsVectorLayerSimpleLabeling(settings))
        names[kind] = lyr

    flood = vector(ROOT / "data/Impact-Assessment-Shashi-Ashim/Inundation/Inundation.shp", "Flood inundation")
    flood.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
        {"color": FLOOD, "outline_color": FLOOD, "outline_width": "0.35"})))

    frames = vector(ROOT / "analysis/inputs/inset_frames.geojson", "Inset areas (panels c-e)")
    c = QColor(BAND)
    frames.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
        {"color": f"{c.red()},{c.green()},{c.blue()},110", "outline_color": BAND_EDGE, "outline_width": "0.4"})))

    # inset letters (c)-(e): a label at a chosen vertex of each frame (labels stay upright on the rotated map)
    letters = QgsVectorLayer("Point?crs=EPSG:32645&field=text:string&field=quad:string", "Inset letters", "memory")
    to_utm_frames = QgsCoordinateTransform(frames.crs(), utm, project)
    feats = []
    for f in frames.getFeatures():
        g = QgsGeometry(f.geometry())
        g.transform(to_utm_frames)
        bb = g.boundingBox()
        vertex, quad = LETTER_SPOT.get(f["panel"], ("top-left", "AboveLeft"))
        x = bb.xMinimum() if "left" in vertex else bb.xMaximum()
        y = bb.yMaximum() if "top" in vertex else bb.yMinimum()
        nf = QgsFeature(letters.fields())
        nf.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
        nf.setAttributes([LETTER_FMT.format(f["panel"]), quad])
        feats.append(nf)
    letters.dataProvider().addFeatures(feats)
    letters.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({"name": "circle", "size": "0",
                                                                             "color": "0,0,0,0", "outline_style": "no"})))
    label_layer(letters, '"text"', text_format(FONT_PT["frame_letter"], INK, bold=True, buffer=0.7),
                placement=Qgis.LabelPlacement.OverPoint, dist=0.6, priority=10,
                extra={QgsPalLayerSettings.Property.OffsetQuad:
                       "CASE \"quad\" WHEN 'AboveLeft' THEN 0 WHEN 'AboveRight' THEN 2 WHEN 'BelowLeft' THEN 6 "
                       "WHEN 'BelowRight' THEN 8 ELSE 0 END"})
    letter_settings = letters.labeling().settings()
    letter_settings.displayAll = True  # the inset letters must always show
    letters.setLabeling(QgsVectorLayerSimpleLabeling(letter_settings))

    ticks = vector(INTER / "flow_path" / "flow_path_km_ticks.shp", "Distance from source (km)",
                   subset='"km" IN (0, 20, 40, 60, 80, 100, 120, 140, 160)')
    rules(ticks, [
        ("Flood source", '"km" = 0', QgsMarkerSymbol.createSimple(
            {"name": "star", "color": "#ffd23f", "outline_color": INK, "outline_width": "0.25", "size": "3.4"})),
        ("Distance from source, every 20 km", '"km" > 0', QgsMarkerSymbol.createSimple(
            {"name": "circle", "color": "white", "outline_color": INK, "outline_width": "0.3", "size": "1.6"})),
    ])
    label_layer(ticks, "CASE WHEN \"km\" = 0 THEN 'Flood source' ELSE \"km\" || ' km' END",
                text_format(FONT_PT["km"], INK, bold=True, buffer=0.6), placement=Qgis.LabelPlacement.AroundPoint,
                dist=0.6, priority=9)

    # same places and spelling as panel (b): towns.geojson also holds places added from inputs/arrival_times.csv
    towns = vector(INTER / "towns.geojson", "Towns", subset="\"name\" IN (" + ", ".join(f"'{t}'" for t in TOWNS) + ")")
    towns.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": INK, "outline_color": "white", "outline_width": "0.2", "size": "1.4"})))
    label_layer(towns, '"name"',
                text_format(FONT_PT["town"], INK, buffer=0.7), placement=Qgis.LabelPlacement.AroundPoint,
                dist=0.7, priority=8)

    hydro = vector(INTER / "hydropower.geojson", "Hydropower structure damaged")
    hydro.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "square", "color": DESTROYED, "outline_color": "white", "outline_width": "0.25", "size": "2.2"})))

    bridges = vector(INTER / "bridges.geojson", "Bridges", subset="\"status\" IN ('Destroyed', 'Damaged')")
    tri = lambda col: QgsMarkerSymbol.createSimple(
        {"name": "triangle", "angle": "180", "color": col, "outline_color": "white", "outline_width": "0.15", "size": "1.8"})
    rules(bridges, [("Bridge washed away", "\"status\" = 'Destroyed'", tri(DESTROYED)),
                    ("Bridge damaged", "\"status\" = 'Damaged'", tri(DAMAGED))])

    flow = vector(INTER / "flow_path" / "flow_path.geojson", "Flow path")
    flow.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({"line_color": FLOOD, "line_width": "0.3"})))

    # ---------------- imagery and inset layers (off by default) ----------------
    s2 = [QgsRasterLayer(str(p), f"Sentinel-2 {p.stem.split('truecolor_')[1].replace('_', ' to ')}")
          for p in sorted((QP / "imagery" / "sentinel2").glob("*.tif"))]
    vantor = [QgsRasterLayer(str(p), f"Vantor {p.stem.rsplit('_', 1)[0].replace('_', ' ')}")
              for p in sorted((QP / "imagery" / "vantor").glob("*.tif"))]
    footprints = vector(QP / "imagery" / "vantor" / "vantor_footprints.geojson", "Vantor scene footprints (all)")
    footprints.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
        {"color": "0,0,0,0", "outline_color": "#7b3294", "outline_width": "0.3"})))

    # ---------------- locator ----------------
    countries = vector(f"/vsizip/{QP / 'basemap' / 'ne_50m_admin_0_countries.zip'}/ne_50m_admin_0_countries.shp",
                       "Countries (Natural Earth)")
    rules(countries, [
        ("Nepal", "\"NAME\" = 'Nepal'", QgsFillSymbol.createSimple(
            {"color": "#d4d4d4", "outline_color": "#6e6e6e", "outline_width": "0.2"})),
        ("Other", "\"NAME\" <> 'Nepal'", QgsFillSymbol.createSimple(
            {"color": "#f5f5f5", "outline_color": "#a6a6a6", "outline_width": "0.15"})),
    ])

    # ---------------- layer tree ----------------
    for child in list(tree.children()):
        tree.removeChildNode(child)

    def group(name, layers, visible=True):
        g = tree.addGroup(name)
        for lyr in layers:
            if not project.mapLayer(lyr.id()):
                project.addMapLayer(lyr, False)
            g.addLayer(lyr)
        g.setItemVisibilityCheckedRecursive(visible)
        return g

    overview_layers = [letters, names["country"], names["district"], towns, ticks, frames, hydro, bridges, flood,
                       districts, hill]  # top to bottom
    group("Overview map (panel a)", overview_layers)
    group("Locator", [countries], visible=False)
    group("Inset layers (panels c-e)", keep_roads + [flow], visible=False)
    group("Imagery - Vantor (panels c-e)", [footprints] + vantor, visible=False)
    group("Imagery - Sentinel-2", s2 + keep_wms, visible=False)

    # ---------------- layout ----------------
    MM = Qgis.LayoutUnit.Millimeters
    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName(LAYOUT_NAME)
    project.layoutManager().addLayout(layout)
    layout.pageCollection().page(0).setPageSize(QgsLayoutSize(*PAGE, MM))

    # map extent: rotate the corridor into page orientation, scale it to the page width, sit it on the
    # bottom margin, then rotate the page centre back to find the (unrotated) extent QGIS expects
    pivot = corridor.boundingBox().center()
    turned = QgsGeometry(corridor)
    turned.rotate(MAP_ROTATION, pivot)  # QGIS rotates clockwise for positive angles, as the map item does
    tb = turned.boundingBox()
    scale = tb.width() / (PAGE[0] - 2 * CORRIDOR_MARGIN[0])  # metres per page mm
    centre = QgsGeometry.fromPointXY(QgsPointXY(tb.xMinimum() + (PAGE[0] / 2 - CORRIDOR_MARGIN[0]) * scale,
                                                tb.yMinimum() + (PAGE[1] / 2 - CORRIDOR_MARGIN[1]) * scale))
    centre.rotate(-MAP_ROTATION, pivot)
    cx, cy = centre.asPoint().x(), centre.asPoint().y()
    m = QgsLayoutItemMap(layout)
    m.attemptMove(QgsLayoutPoint(0, 0, MM))
    m.attemptResize(QgsLayoutSize(*PAGE, MM))
    m.setCrs(utm)
    m.setExtent(QgsRectangle(cx - PAGE[0] * scale / 2, cy - PAGE[1] * scale / 2,
                             cx + PAGE[0] * scale / 2, cy + PAGE[1] * scale / 2))
    m.setMapRotation(MAP_ROTATION)
    m.setLayers(overview_layers)
    m.setKeepLayerSet(True)
    m.setFrameEnabled(False)
    m.setBackgroundEnabled(False)
    layout.addLayoutItem(m)

    letter = QgsLayoutItemLabel(layout)
    letter.setText(LETTER_FMT.format("a"))
    letter.setTextFormat(text_format(FONT_PT["letter"], INK, bold=True))
    letter.attemptMove(QgsLayoutPoint(*LETTER_POS, MM))
    letter.attemptResize(QgsLayoutSize(10, 5, MM))
    layout.addLayoutItem(letter)

    sb = QgsLayoutItemScaleBar(layout)
    sb.setStyle("Single Box")
    sb.setLinkedMap(m)
    sb.applyDefaultSize(Qgis.DistanceUnit.Kilometers)  # resets units, so set everything after it
    sb.setUnits(Qgis.DistanceUnit.Kilometers)
    sb.setUnitLabel("km")
    sb.setUnitsPerSegment(SCALEBAR_KM)
    sb.setNumberOfSegments(2)
    sb.setNumberOfSegmentsLeft(0)
    sb.setHeight(1.1)
    sb.setTextFormat(text_format(FONT_PT["scalebar"], INK2))
    sb.resizeToMinimumWidth()
    layout.addLayoutItem(sb)
    sb.attemptMove(QgsLayoutPoint(*SCALEBAR_POS, MM))

    arrow = QgsLayoutItemPicture(layout)
    arrow.setPicturePath(":/images/north_arrows/layout_default_north_arrow.svg")
    arrow.setSvgFillColor(QColor(INK2))
    arrow.setSvgStrokeColor(QColor(INK2))
    arrow.attemptMove(QgsLayoutPoint(*NORTH_POS, MM))
    arrow.attemptResize(QgsLayoutSize(4.0, 6.5, MM))
    arrow.setSvgStrokeWidth(0.25)
    arrow.setLinkedMap(m)  # turns with the map, so it points to north on the rotated map
    layout.addLayoutItem(arrow)
    north = QgsLayoutItemLabel(layout)  # "N" just beyond the tip, along the rotated arrow
    north.setText("N")
    north.setTextFormat(text_format(FONT_PT["scalebar"], INK2, bold=True))
    north.setMargin(0)
    north.adjustSizeToText()
    north.setReferencePoint(QgsLayoutItem.ReferencePoint.Middle)
    ax_, ay_ = NORTH_POS[0] + 2.0, NORTH_POS[1] + 3.25
    north.attemptMove(QgsLayoutPoint(ax_ + 4.6 * math.sin(math.radians(MAP_ROTATION)),
                                     ay_ - 4.6 * math.cos(math.radians(MAP_ROTATION)), MM))
    layout.addLayoutItem(north)

    lx, ly, lw, lh = LOCATOR_BOX
    loc = QgsLayoutItemMap(layout)
    loc.attemptMove(QgsLayoutPoint(lx, ly, MM))
    loc.attemptResize(QgsLayoutSize(lw, lh, MM))
    loc.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    lcx, lcy, lwd = 84.2, 28.4, 11.0
    lhd = lwd * lh / lw
    loc.setExtent(QgsRectangle(lcx - lwd / 2, lcy - lhd / 2, lcx + lwd / 2, lcy + lhd / 2))
    loc.setLayers([countries])
    loc.setKeepLayerSet(True)
    loc.setFrameEnabled(True)
    loc.setFrameStrokeWidth(mm(0.25))
    loc.setFrameStrokeColor(QColor(INK2))
    loc.setBackgroundColor(QColor("#dde9f0"))
    layout.addLayoutItem(loc)
    ov = QgsLayoutItemMapOverview("Overview extent", loc)
    loc.overviews().addOverview(ov)
    ov.setLinkedMap(m)  # draws the rotated footprint of panel (a)
    ov.setFrameSymbol(QgsFillSymbol.createSimple({"color": "0,0,0,0", "outline_color": DESTROYED, "outline_width": "0.5"}))
    loc_ext, loc_scale = loc.extent(), loc.extent().width() / lw
    for text, lon, lat in LOCATOR_LABELS:
        lbl = QgsLayoutItemLabel(layout)
        lbl.setText(text)
        lbl.setTextFormat(text_format(FONT_PT["locator"], "#6e6e6e", spacing=0.6))
        lbl.setMargin(0)
        lbl.adjustSizeToText()
        lbl.setReferencePoint(QgsLayoutItem.ReferencePoint.Middle)
        lbl.attemptMove(QgsLayoutPoint(lx + (lon - loc_ext.xMinimum()) / loc_scale,
                                       ly + (loc_ext.yMaximum() - lat) / loc_scale, MM))
        layout.addLayoutItem(lbl)

    credit = QgsLayoutItemLabel(layout)
    credit.setText("Hillshade: Copernicus DEM GLO-30.")
    credit.setTextFormat(text_format(FONT_PT["credit"], MUTED))
    credit.setMode(QgsLayoutItemLabel.Mode.ModeFont)
    credit.adjustSizeToText()
    credit.attemptMove(QgsLayoutPoint(*CREDIT_POS, MM))
    layout.addLayoutItem(credit)

    # the free area where compose_figure.py draws the figure's shared key
    (QP / "exports").mkdir(exist_ok=True)
    (QP / "exports" / "overview_map_layout.json").write_text(json.dumps({
        "page_mm": list(PAGE), "key_box_mm": list(KEY_BOX)}, indent=2))

    import inset_layout  # panels c-e live in the same project, so one run rebuilds both layouts
    insets = inset_layout.build(project)

    project.write(str(PROJECT))

    out = QP / "exports"
    out.mkdir(exist_ok=True)
    exporter = QgsLayoutExporter(layout)
    img = QgsLayoutExporter.ImageExportSettings()
    img.dpi = 600
    pdf = QgsLayoutExporter.PdfExportSettings()
    pdf.rasterizeWholeImage = False
    r1 = exporter.exportToImage(str(out / "overview_map.png"), img)
    r2 = exporter.exportToPdf(str(out / "overview_map.pdf"), pdf)
    print("project saved:", PROJECT, "| backup:", backup.name)
    print("export png:", r1, "| pdf:", r2, "->", out)
    inset_layout.export(insets, out)
    app.exitQgis()


if __name__ == "__main__":
    main()
