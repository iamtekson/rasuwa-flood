# QGIS project: overview map (panel a) and zoomed damage maps (panels c–e)

`overviewmap.qgz` holds two print layouts:

- **"Panel a - overview"** (180 × 78 mm): the flood corridor, rotated 28° clockwise so the river runs left to right, with the hillshade clipped to 5 km either side of the flow path (km 0–165). It shows distance from source every 20 km, towns, damaged hydropower and bridges, the c–e inset frames, districts and the China–Nepal border. The free white space holds the shared key (top, in the dip of the river; drawn by `analysis/scripts/compose_figure.py`), the scale bar and a north arrow that turns with the map (bottom left), and the Nepal locator (bottom right).
- **"Panels c-e"** (180 mm wide, one row): each map shows exactly one inset frame on post-event imagery, with only the damaged features: buildings and roads in the flood inundation, destroyed/damaged bridges, hydropower footprints, the inundation outline and 5-km distance markers. The imagery is shown in greyscale with the hillshade multiplied over it, so the whole figure shares one monochrome base and only the damage is in colour. For natural colour, set `IMAGERY_GREYSCALE = False` and `HILLSHADE_OVERLAY_OPACITY = 0` at the top of `scripts/inset_layout.py` (or keep about 0.2 for a little relief on the colour imagery).

Colours match the damage profile (panel b), in neutral greys to match the manuscript's other distance figures. Text is 7–8 pt (panel letters 10 pt); the sizes are `FONT_PT` at the top of each script.

## Rebuild

Scripts run from the repo root. The QGIS ones use QGIS's own Python (`"C:\Program Files\QGIS 4.0.2\bin\python-qgis.bat" <script>`):

| Order | Script | Writes |
| --- | --- | --- |
| 1 | `uv run analysis/scripts/build_intermediate.py` | layers the map reads from `analysis/intermediate/` |
| 2 | `scripts/build_basemap.py` (QGIS Python) | `basemap/`: Copernicus DEM, hillshade, Natural Earth countries |
| 3 | `scripts/download_vantor_insets.py` (QGIS Python) | `imagery/vantor/`: inset clips and all scene footprints |
| 4 | `uv run qgis_project/scripts/download_sentinel2_insets.py` | `imagery/sentinel2/insets/`: 10 m post-event Sentinel-2 per inset frame (uses your Sentinel Hub layer's configuration); `download_sentinel2_overview.py` does the same for the whole overview |
| 5 | `scripts/build_overview_layout.py` (QGIS Python) | rebuilds the layers and both layouts in `overviewmap.qgz` (panels c–e come from `scripts/inset_layout.py`), exports `exports/overview_map.*` and `exports/panels_c_e.*` (600 dpi PNG and PDF) |

Step 5 backs up the project to `archive/` the first time it runs each day, and rebuilds the layout from scratch. Hand edits made in QGIS are kept only until you re-run it, so either re-run less often or move a setting into the script. Page size, rotation (`MAP_ROTATION`), the positions of the scale bar, north arrow, locator and key box, and colours are constants at the top of `build_overview_layout.py` (panel a; `SHOW_LEGEND` and `LETTER_FMT` also live there — legends are off because the combined figure has one shared key, drawn by `analysis/scripts/compose_figure.py` in the area recorded in `exports/overview_map_layout.json`) and `inset_layout.py` (panels c–e: imagery per panel, colours, line widths `ROAD_W` / `HYDRO_W` / `FLOOD_LINE_W`, hydropower labels, km-marker spacing, scale-bar length and `SCALE_BAR_RAISE` to lift a scale bar off nearby labels). The corridor, the clipped district boundaries and the district and country name positions come from `analysis/intermediate/map_a/` (see `build_intermediate.py`: `CORRIDOR_BUFFER_KM`, `LABEL_CLEAR_KM`, `DISTRICT_LABEL_MIN_KM2`, `DISTRICT_LABEL_FROM_KM`).

## Layer groups

- **Overview map (panel a)**: everything in the layout.
- **Inset layers (panels c–e)**, off: roads inside and within 100 m of the flood inundation, and the flow path.
- **Imagery - Vantor (panels c–e)**, off: inset clips and footprints of all 33 Vantor scenes. Each footprint has a `vsicurl` URL, so any other scene can be streamed straight into QGIS (Layer > Add Raster Layer, paste the URL).
- **Imagery - Sentinel-2**, off: two local mosaics and your Sentinel Hub WMS layers.
- **Locator**, off: used only by the locator map.

The inset frames come from `analysis/inputs/inset_frames.geojson`, the same file that draws the c–e bands on panel (b) and sets the extent of each map in panels c–e. Edit the frames there, re-run step 1, step 3 (to re-cut the imagery) and step 5, and all three panels follow. The frames are square (`FRAME_ASPECT = 1.0` in `build_intermediate.py`), so panels c–e share one height and sit in one 64 mm row.

## Imagery and data

| Folder | Content | Source and licence |
| --- | --- | --- |
| `imagery/vantor/` | `c_post_2026-08-27_WV03` (0.31 m), `c_pre_2023-09-17_GE01`, `d_pre_2024-05-29_WV02`, `e_post_2026-09-08_WV02` (0.48 m, two tiles of one pass merged), `e_pre_2026-02-05_LG06`; native resolution, cut to each inset frame | Vantor Open Data, Nepal-Flooding-Aug-2026, CC BY-NC 4.0 |
| `imagery/sentinel2/` | post-event true colour: 46 m overview mosaics (cloudy, not used) and 10 m per inset frame in `insets/` (panel d, and gap fill under c and e) | Copernicus Sentinel-2 (via Copernicus Data Space) |
| `basemap/` | DEM and hillshade, 30 m | Copernicus DEM GLO-30, © DLR e.V. 2010–2014 and © Airbus Defence and Space GmbH 2014–2018, provided under COPERNICUS by the EU and ESA |
| `basemap/` | country outlines (locator) | Natural Earth, public domain |

Panel d (Upper Trishuli hydropower cluster) has **no post-event Vantor coverage** (only 2021 and 2024 pre-event scenes), so it uses 10 m post-event Sentinel-2. To use Planet instead, set `IMAGERY` at the top of `scripts/inset_layout.py`.

Frame e covers km 67–79 (Trishuli–Bidur) rather than starting at Betrawati: that stretch lies entirely inside the clear 8 Sep 2026 Vantor pass, so the panel has no imagery seams.
