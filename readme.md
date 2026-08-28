There was a very massive flash flood in Bhotekoshi River (which merged to Trisuli River) in August 26th, 2026. We have few sources of information related to this flood as below. 

## Interactive map

`index.html` is a static HTML/CSS/vanilla-JS page built with MapLibre GL JS. It needs to be served over HTTP (not opened as a `file://` path) because it `fetch()`s `config/layers.json`, the icon SVGs, and the local GeoJSON files, which browsers block under `file://`.

**Portal URL**: https://iamtekson.github.io/rasuwa-flood/

**Layout:**
- `config/layers.json` — the single source of truth for map categories/layers (colors, icons, which layers are active by default). Edit this to add/remove/restyle layers — no code changes needed.
- `map_icons/` — SVG icons used by point layers (bridge, education, health, video, hazard/glacier pins).
- `data/` — all GeoJSON data files.
- `js/main.js`, `css/style.css` — the app itself.

**Features:** pan/zoom with a 3D-terrain default view (pitched + rotated to align with the river valley; toggle back to flat top-down with the "3D Terrain" button), a before/after imagery compare slider, category-grouped layer toggles, icon-coded point layers (bridge/education/health/video/hazard symbols), auto-open callout popups for a few highlighted features (potential flood origin, Langtang glacier area, a few flood-adjacent settlements), auto-zoom to the flood extent, and a click-to-play popup on the eyewitness-video points.


