"""Build the overview map (figure panel a) in qgis_project/overviewmap.qgz and export it.

Run with QGIS's Python (after analysis/scripts/build_intermediate.py and build_basemap.py):
    "C:\\Program Files\\QGIS 4.0.2\\bin\\python-qgis.bat" qgis_project\\scripts\\build_overview_layout.py

What it does:
  - backs up the current project to qgis_project/archive/
  - restyles / adds the layers and sorts them into groups (overview, imagery, inset layers, locator)
  - creates the print layout "Panel a - overview" (180 x 82 mm): main map, graticule, scale bar,
    north arrow, Nepal locator, legend
  - exports qgis_project/exports/overview_map.png (600 dpi) and .pdf
Colours match the damage profile (panel b). Re-running rebuilds the layout from scratch.
"""
import shutil
from datetime import date
from pathlib import Path

from qgis.core import (Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsLayoutItem,
                       QgsPointXY, QgsFillSymbol, QgsLayerTreeGroup,
                       QgsLayerTreeLayer, QgsLayoutExporter, QgsLayoutItemLabel, QgsLayoutItemLegend, QgsLayoutItemMap,
                       QgsLayoutItemMapGrid, QgsLayoutItemMapOverview, QgsLayoutItemPicture, QgsLayoutItemScaleBar,
                       QgsLayoutMeasurement, QgsLayoutPoint, QgsLayoutSize, QgsLegendStyle, QgsLineSymbol,
                       QgsMarkerSymbol, QgsPalLayerSettings, QgsPrintLayout, QgsSimpleLineSymbolLayer, QgsProject, QgsProperty, QgsRasterLayer,
                       QgsRectangle, QgsRuleBasedRenderer, QgsSingleSymbolRenderer, QgsTextBufferSettings,
                       QgsTextFormat, QgsVectorLayer, QgsVectorLayerSimpleLabeling, QgsLegendRenderer)
from qgis.PyQt.QtGui import QColor, QFont

ROOT = Path(__file__).resolve().parents[2]
QP = ROOT / "qgis_project"
PROJECT = QP / "overviewmap.qgz"
INTER = ROOT / "analysis" / "intermediate"
LAYOUT_NAME = "Panel a - overview"

# Page and item geometry (mm). The map extent keeps the map item's aspect ratio.
PAGE = (180, 82)
MAP = (5.5, 0.5, 115.5, 76.5)        # x, y, w, h
COL_X, COL_W = 124, 56               # right-hand column: locator + legend
MAP_CENTER = (306811, 3106281)       # EPSG:32645, centre of the flood corridor (source to Mugling)
MAP_WIDTH_M = 106000
COUNTRY_LABELS = [("CHINA", 85.33, 28.36), ("NEPAL", 85.47, 28.21)]  # checked against the district polygons
LOCATOR_LABELS = [("CHINA", 85.0, 30.4), ("NEPAL", 82.3, 28.75), ("INDIA", 82.6, 26.6)]
LETTER_CORNER = {"c": "bottom-left"}  # where each inset letter sits; default top-left, outside the frame
DISTRICT_LABELS = [("RASUWA", 85.48, 28.12), ("NUWAKOT", 85.34, 27.94), ("DHADING", 84.95, 27.97), ("GORKHA", 84.72, 28.15)]
TOWNS = ["Rasuwagadhi", "Syabrubesi", "Betrawati", "Bidur", "Devighat", "Malekhu", "Mugling"]

INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
FLOOD = "#2b7bb9"
DESTROYED, DAMAGED = "#d03b3b", "#ec835a"
BAND, BAND_EDGE = "#e9e2cc", "#6e6450"
DISTRICT = "#4a4136"  # district names
# District boundary line: colour, width (mm) and dash pattern (dash;gap;dot;gap, mm); the white edging under it
# keeps it readable on dark slopes (last value = opacity 0-255).
BOUNDARY_COLOR, BOUNDARY_WIDTH, BOUNDARY_DASH = "#8a8174", 0.3, "2.4;0.9;0.5;0.9"
BOUNDARY_EDGING = "255,255,255,120"
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
    hill = QgsRasterLayer(str(QP / "basemap" / "hillshade_multidirectional.tif"), "Hillshade (Copernicus DEM GLO-30)")
    hill.renderer().setOpacity(0.5)  # a light hillshade so the corridor and damage symbols stand out

    districts = vector(f"/vsizip/{ROOT / 'data/OSM/2. Administrative layer/AOI_Affected_district_v1.zip'}"
                       "/AOI_Affected_district_v1/affected_district.geojson", "District boundaries")
    # dash-dot boundary on a faint white casing, so it reads on light and dark hillshade alike
    boundary = QgsFillSymbol()
    boundary.deleteSymbolLayer(0)
    boundary.appendSymbolLayer(QgsSimpleLineSymbolLayer.create(
        {"line_color": BOUNDARY_EDGING, "line_width": "0.9", "capstyle": "round", "joinstyle": "round"}))
    boundary.appendSymbolLayer(QgsSimpleLineSymbolLayer.create(
        {"line_color": BOUNDARY_COLOR, "line_width": str(BOUNDARY_WIDTH), "use_custom_dash": "1", "customdash": BOUNDARY_DASH,
         "customdash_unit": "MM", "capstyle": "flat", "joinstyle": "round"}))
    districts.setRenderer(QgsSingleSymbolRenderer(boundary))

    flood = vector(ROOT / "data/Impact-Assessment-Shashi-Ashim/Inundation/Inundation.shp", "Flood inundation")
    flood.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
        {"color": FLOOD, "outline_color": FLOOD, "outline_width": "0.35"})))

    frames = vector(ROOT / "analysis/inputs/inset_frames.geojson", "Inset areas (panels c-e)")
    c = QColor(BAND)
    frames.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
        {"color": f"{c.red()},{c.green()},{c.blue()},110", "outline_color": BAND_EDGE, "outline_width": "0.4"})))

    ticks = vector(INTER / "flow_path" / "flow_path_km_ticks.shp", "Distance from source (km)",
                   subset='"km" IN (0, 20, 40, 60, 80, 100, 120, 140, 160)')
    rules(ticks, [
        ("Flood source", '"km" = 0', QgsMarkerSymbol.createSimple(
            {"name": "star", "color": "#ffd23f", "outline_color": INK, "outline_width": "0.25", "size": "3.2"})),
        ("Distance from source, every 20 km", '"km" > 0', QgsMarkerSymbol.createSimple(
            {"name": "circle", "color": "white", "outline_color": INK, "outline_width": "0.3", "size": "1.5"})),
    ])
    label_layer(ticks, "CASE WHEN \"km\" = 0 THEN 'Flood source' ELSE \"km\" || ' km' END",
                text_format(6, INK, bold=True, buffer=0.6), placement=Qgis.LabelPlacement.AroundPoint, dist=0.6, priority=9)

    towns_filter = " OR ".join(f"\"name_en\" LIKE '{t}%'" for t in TOWNS)
    towns = vector(ROOT / "data" / "cities.geojson", "Towns", subset=towns_filter)
    towns.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": INK, "outline_color": "white", "outline_width": "0.2", "size": "1.3"})))
    label_layer(towns, "regexp_replace(\"name_en\", '\\\\s*\\\\(.*\\\\)$', '')", text_format(6.5, INK, buffer=0.7),
                placement=Qgis.LabelPlacement.AroundPoint, dist=0.7, priority=8)

    hydro = vector(INTER / "hydropower.geojson", "Hydropower structure, fully damaged")
    hydro.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "square", "color": DESTROYED, "outline_color": "white", "outline_width": "0.25", "size": "2.1"})))

    bridges = vector(INTER / "bridges.geojson", "Bridges", subset="\"status\" IN ('Destroyed', 'Damaged')")
    tri = lambda col: QgsMarkerSymbol.createSimple(
        {"name": "triangle", "angle": "180", "color": col, "outline_color": "white", "outline_width": "0.15", "size": "1.7"})
    rules(bridges, [("Bridge destroyed, washed away", "\"status\" = 'Destroyed'", tri(DESTROYED)),
                    ("Bridge damaged, needs repair", "\"status\" = 'Damaged'", tri(DAMAGED))])

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
            {"color": "#d6d2c6", "outline_color": "#6f6c64", "outline_width": "0.2"})),
        ("Other", "\"NAME\" <> 'Nepal'", QgsFillSymbol.createSimple(
            {"color": "#f6f5f1", "outline_color": "#a9a69d", "outline_width": "0.15"})),
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

    overview_layers = [towns, ticks, frames, hydro, bridges, flood, districts, hill]  # top to bottom
    group("Overview map (panel a)", overview_layers)
    group("Locator", [countries], visible=False)
    group("Inset layers (panels c-e)", keep_roads + [flow], visible=False)
    group("Imagery - Vantor (panels c-e)", [footprints] + vantor, visible=False)
    group("Imagery - Sentinel-2", s2 + keep_wms, visible=False)

    # ---------------- layout ----------------
    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName(LAYOUT_NAME)
    project.layoutManager().addLayout(layout)
    layout.pageCollection().page(0).setPageSize(QgsLayoutSize(*PAGE, Qgis.LayoutUnit.Millimeters))
    utm = QgsCoordinateReferenceSystem("EPSG:32645")

    m = QgsLayoutItemMap(layout)
    m.attemptMove(QgsLayoutPoint(MAP[0], MAP[1], Qgis.LayoutUnit.Millimeters))
    m.attemptResize(QgsLayoutSize(MAP[2], MAP[3], Qgis.LayoutUnit.Millimeters))
    m.setCrs(utm)
    h = MAP_WIDTH_M * MAP[3] / MAP[2]
    m.setExtent(QgsRectangle(MAP_CENTER[0] - MAP_WIDTH_M / 2, MAP_CENTER[1] - h / 2,
                             MAP_CENTER[0] + MAP_WIDTH_M / 2, MAP_CENTER[1] + h / 2))
    m.setLayers(overview_layers)
    m.setKeepLayerSet(True)
    m.setFrameEnabled(True)
    m.setFrameStrokeWidth(mm(0.25))
    m.setFrameStrokeColor(QColor(INK2))
    layout.addLayoutItem(m)

    grid = QgsLayoutItemMapGrid("Graticule", m)
    m.grids().addGrid(grid)
    grid.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    grid.setIntervalX(0.25)
    grid.setIntervalY(0.25)
    grid.setStyle(Qgis.MapGridStyle.Lines)
    grid.setLineSymbol(QgsLineSymbol.createSimple({"line_color": "255,255,255,150", "line_width": "0.15"}))
    grid.setAnnotationEnabled(True)
    grid.setAnnotationFormat(Qgis.MapGridAnnotationFormat.DegreeMinutePadded)
    grid.setAnnotationPrecision(0)
    grid.setAnnotationTextFormat(text_format(5.5, INK2))
    V = Qgis.MapGridComponentVisibility
    for side, show, direction in [(Qgis.MapGridBorderSide.Left, V.LatitudeOnly, Qgis.MapGridAnnotationDirection.VerticalDescending),
                                  (Qgis.MapGridBorderSide.Bottom, V.LongitudeOnly, Qgis.MapGridAnnotationDirection.Horizontal),
                                  (Qgis.MapGridBorderSide.Right, V.HideAll, Qgis.MapGridAnnotationDirection.Horizontal),
                                  (Qgis.MapGridBorderSide.Top, V.HideAll, Qgis.MapGridAnnotationDirection.Horizontal)]:
        grid.setAnnotationDisplay(show, side)
        grid.setAnnotationPosition(Qgis.MapGridAnnotationPosition.OutsideMapFrame, side)
        grid.setAnnotationDirection(direction, side)
    grid.setAnnotationFrameDistance(0.8)
    grid.setFrameStyle(Qgis.MapGridFrameStyle.ExteriorTicks)
    grid.setFrameWidth(1.0)
    grid.setFramePenSize(0.2)
    grid.setFramePenColor(QColor(INK2))
    m.updateBoundingRect()

    to_utm = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"), utm, project)
    ext = m.extent()
    scale = ext.width() / MAP[2]  # metres per mm on the page

    def geo_label(text, x, y, fmt, anchor=QgsLayoutItem.ReferencePoint.Middle, lonlat=True):
        """A layout label pinned to a map position (the map extent is fixed)."""
        if lonlat:
            pt = to_utm.transform(QgsPointXY(x, y))
            x, y = pt.x(), pt.y()
        lbl = QgsLayoutItemLabel(layout)
        lbl.setText(text)
        lbl.setTextFormat(fmt)
        lbl.setMargin(0)
        lbl.adjustSizeToText()
        lbl.setReferencePoint(anchor)
        lbl.attemptMove(QgsLayoutPoint(MAP[0] + (x - ext.xMinimum()) / scale, MAP[1] + (ext.yMaximum() - y) / scale,
                                       Qgis.LayoutUnit.Millimeters))
        layout.addLayoutItem(lbl)
        return lbl

    country_fmt = text_format(6.5, "#5c5952", bold=True, spacing=1.2, buffer=0.6)
    for text, lon, lat in COUNTRY_LABELS:
        geo_label(text, lon, lat, country_fmt)
    district_fmt = text_format(6.3, DISTRICT, bold=True, spacing=1.0, buffer=0.8)
    for text, lon, lat in DISTRICT_LABELS:
        geo_label(text, lon, lat, district_fmt)
    letter_fmt = text_format(8.5, INK, bold=True, buffer=0.7)
    for f in frames.getFeatures():  # letter just outside each inset frame's top-left corner
        g = QgsGeometry(f.geometry())
        g.transform(to_utm)
        bb = g.boundingBox()
        if LETTER_CORNER.get(f["panel"]) == "bottom-left":
            geo_label(f["panel"], bb.xMinimum() - 250, bb.yMinimum() - 250, letter_fmt,
                      anchor=QgsLayoutItem.ReferencePoint.UpperRight, lonlat=False)
        else:
            geo_label(f["panel"], bb.xMinimum() - 250, bb.yMaximum() + 250, letter_fmt,
                      anchor=QgsLayoutItem.ReferencePoint.LowerRight, lonlat=False)

    letter = QgsLayoutItemLabel(layout)
    letter.setText("a")
    letter.setTextFormat(text_format(9, INK, bold=True, buffer=0.8))
    letter.attemptMove(QgsLayoutPoint(MAP[0] + 1.2, MAP[1] + 0.8, Qgis.LayoutUnit.Millimeters))
    letter.attemptResize(QgsLayoutSize(5, 5, Qgis.LayoutUnit.Millimeters))
    layout.addLayoutItem(letter)

    arrow = QgsLayoutItemPicture(layout)
    arrow.setPicturePath(":/images/north_arrows/layout_default_north_arrow.svg")
    arrow.setSvgFillColor(QColor(INK2))
    arrow.setSvgStrokeColor(QColor(INK2))
    arrow.attemptMove(QgsLayoutPoint(MAP[0] + MAP[2] - 37, MAP[1] + MAP[3] - 9.5, Qgis.LayoutUnit.Millimeters))
    arrow.attemptResize(QgsLayoutSize(3.2, 5.5, Qgis.LayoutUnit.Millimeters))
    arrow.setLinkedMap(m)
    arrow.setBackgroundEnabled(True)
    arrow.setBackgroundColor(QColor(255, 255, 255, 190))
    layout.addLayoutItem(arrow)

    sb = QgsLayoutItemScaleBar(layout)
    sb.setStyle("Single Box")
    sb.setLinkedMap(m)
    sb.applyDefaultSize(Qgis.DistanceUnit.Kilometers)  # resets units, so set everything after it
    sb.setUnits(Qgis.DistanceUnit.Kilometers)
    sb.setUnitLabel("km")
    sb.setUnitsPerSegment(10)
    sb.setNumberOfSegments(2)
    sb.setNumberOfSegmentsLeft(0)
    sb.setHeight(1.0)
    sb.setTextFormat(text_format(5.5, INK2, buffer=0.5))
    sb.resizeToMinimumWidth()
    layout.addLayoutItem(sb)
    sb.attemptMove(QgsLayoutPoint(MAP[0] + MAP[2] - 31, MAP[1] + MAP[3] - 8.5, Qgis.LayoutUnit.Millimeters))

    loc = QgsLayoutItemMap(layout)
    loc.attemptMove(QgsLayoutPoint(COL_X, MAP[1], Qgis.LayoutUnit.Millimeters))
    loc.attemptResize(QgsLayoutSize(COL_W, 33, Qgis.LayoutUnit.Millimeters))
    loc.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    cx, cy, w = 84.2, 28.4, 9.6
    hh = w * 33 / COL_W
    loc.setExtent(QgsRectangle(cx - w / 2, cy - hh / 2, cx + w / 2, cy + hh / 2))
    loc.setLayers([countries])
    loc.setKeepLayerSet(True)
    loc.setFrameEnabled(True)
    loc.setFrameStrokeWidth(mm(0.25))
    loc.setFrameStrokeColor(QColor(INK2))
    loc.setBackgroundColor(QColor("#dde9f0"))
    layout.addLayoutItem(loc)
    ov = QgsLayoutItemMapOverview("Overview extent", loc)
    loc.overviews().addOverview(ov)
    ov.setLinkedMap(m)
    ov.setFrameSymbol(QgsFillSymbol.createSimple({"color": "0,0,0,0", "outline_color": DESTROYED, "outline_width": "0.5"}))

    loc_ext, loc_scale = loc.extent(), loc.extent().width() / COL_W
    for text, lon, lat in LOCATOR_LABELS:
        lbl = QgsLayoutItemLabel(layout)
        lbl.setText(text)
        lbl.setTextFormat(text_format(5.5, "#6f6c64", spacing=0.6))
        lbl.setMargin(0)
        lbl.adjustSizeToText()
        lbl.setReferencePoint(QgsLayoutItem.ReferencePoint.Middle)
        lbl.attemptMove(QgsLayoutPoint(COL_X + (lon - loc_ext.xMinimum()) / loc_scale,
                                       MAP[1] + (loc_ext.yMaximum() - lat) / loc_scale, Qgis.LayoutUnit.Millimeters))
        layout.addLayoutItem(lbl)

    legend = QgsLayoutItemLegend(layout)
    legend.setLinkedMap(m)
    if hasattr(legend, "setSyncMode"):
        legend.setSyncMode(Qgis.LegendSyncMode.Manual)
    else:
        legend.setAutoUpdateModel(False)
    legend.setTitle("")
    root = legend.model().rootGroup()
    root.removeAllChildren()
    for lyr in [flood, ticks, towns, hydro, bridges, frames, districts]:
        node = root.addLayer(lyr)
        if lyr in (ticks, bridges):
            QgsLegendRenderer.setNodeLegendStyle(node, QgsLegendStyle.Style.Hidden)
    for style in (QgsLegendStyle.Style.SymbolLabel, QgsLegendStyle.Style.Subgroup):
        legend.rstyle(style).setTextFormat(text_format(6, INK2))
    legend.setSymbolWidth(4.0)
    legend.setSymbolHeight(2.4)
    legend.rstyle(QgsLegendStyle.Style.Symbol).setMargin(QgsLegendStyle.Side.Top, 0.9)
    legend.setBoxSpace(0)
    legend.setBackgroundEnabled(False)
    legend.setFrameEnabled(False)
    legend.attemptMove(QgsLayoutPoint(COL_X, MAP[1] + 35, Qgis.LayoutUnit.Millimeters))
    legend.setResizeToContents(True)
    layout.addLayoutItem(legend)
    legend.adjustBoxSize()

    credit = QgsLayoutItemLabel(layout)
    credit.setText("Hillshade: Copernicus DEM GLO-30.")
    credit.setTextFormat(text_format(4.8, MUTED))
    credit.setMode(QgsLayoutItemLabel.Mode.ModeFont)
    credit.attemptMove(QgsLayoutPoint(COL_X, PAGE[1] - 7.5, Qgis.LayoutUnit.Millimeters))
    credit.attemptResize(QgsLayoutSize(COL_W, 7, Qgis.LayoutUnit.Millimeters))
    layout.addLayoutItem(credit)

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
