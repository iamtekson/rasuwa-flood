There was a very massive flash flood in Bhotekoshi River (which merged to Trisuli River) in August 26th, 2026. We have few sources of information related to this flood as below. 

## Interactive map

`index.html` is a static HTML/CSS/vanilla-JS page built with MapLibre GL JS. It needs to be served over HTTP (not opened as a `file://` path) because it `fetch()`s `config/layers.json`, the icon SVGs, and the local GeoJSON files, which browsers block under `file://`.

**Portal URL**: https://iamtekson.github.io/rasuwa-flood/

**Layout:**
- `config/layers.json` — the single source of truth for map categories/layers (colors, icons, which layers are active by default). Edit this to add/remove/restyle layers — no code changes needed.
- `map_icons/` — SVG icons used by point layers (bridge, education, health, video, hazard/glacier pins).
- `data/` — all GeoJSON data files.
- `css/style.css` — all styling.
- `js/` — the app, split into small ES modules (native browser `import`/`export`, no build step):
  - `main.js` — entry point, just wires everything together.
  - `state.js` — shared app state (the map instance, config, etc.).
  - `utils.js` — pure helpers: caching, GeoJSON normalization, color/label resolution, geometry math.
  - `icons.js` — loads the SVG icons into MapLibre.
  - `layers.js` — the generic add/remove logic for every layer type.
  - `popups.js` — hover/click popups and the always-open "highlight" callouts.
  - `sidebar.js` — builds the layer-toggle sidebar.
  - `stats.js` — the 📊 legend + feature-count panel.
  - `compare.js` — the before/after imagery swipe.
  - `map-core.js` — map creation, base style, 3D-terrain toggle, topbar wiring.

**Features:** pan/zoom with a 3D-terrain default view (pitched + rotated to align with the river valley; toggle back to flat top-down with the "3D Terrain" button), a before/after imagery compare slider, category-grouped layer toggles, icon-coded point layers (bridge/education/health/video/hazard symbols), auto-open callout popups for a few highlighted features (potential flood origin, Langtang glacier area, a few flood-adjacent settlements), auto-zoom to the flood extent, a click-to-play popup on the eyewitness-video points, and a 📊 button on each layer that shows its legend plus a feature-count breakdown.

## Contributing a layer

Got a useful GeoJSON layer (a shapefile export, an HDX/OSM extract, anything)? You don't need to touch any code — everything is driven by `config/layers.json`.

1. Drop your file in `data/` as GeoJSON. If it came from a shapefile/QGIS export, it needs to be a `FeatureCollection` of `Feature`s (not a bare `GeometryCollection` — some exporters produce that shape, and the app will now auto-fix it on load, but a real `FeatureCollection` is still the safer target). Coordinates must be plain lon/lat (EPSG:4326); reproject first if your source is in a projected CRS like UTM.
2. Add an entry to the relevant category's `layers` array in `config/layers.json` (or add a new category if it genuinely doesn't fit one of the existing ones — but prefer reusing an existing category over adding another).
3. Pick a `type`: `"fill"` (polygons), `"line"`, `"circle"` (points, flat or per-value color), `"icon"` (points with a marker image — add the icon under `map.icons` and reference its id), or `"raster"` (XYZ tile URL).
4. Common optional fields:
   - `labelField` — property shown on hover.
   - `popupFields` — an array of properties shown as a key/value table on hover/click instead of one field. Add `popupLabels` to override how a field name is displayed (e.g. `"GaPa_NaPa": "Municipality"`).
   - `popupTrigger: "click"` — makes the popup only appear on click instead of hover (useful for polygon layers you don't want popping up on every mouse pass).
   - For `circle`/`icon` layers, `paint.circleColor` / `iconColor` can be a flat hex string, or `{ "field": "status", "values": {"A": "#d62728", "B": "#2ca02c"}, "default": "#888" }` to color by a property — this also automatically becomes the legend and the default statistics grouping.
   - `statsField` — overrides which property the 📊 stats panel groups counts by (defaults to the color field if one exists, else `labelField`).
   - `active: true/false` — whether it's on by default.
5. Reload the page (hard-refresh) and check the 📊 button on your new layer — it's the fastest way to confirm the data loaded and see what property values actually look like.

If something doesn't render, open the browser console first — a MapLibre style error (bad paint value, missing property) shows up there immediately.


