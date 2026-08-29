// Map construction, base style, 3D-terrain toggle, and topbar button wiring.
import { state } from "./state.js";
import { loadIcons } from "./icons.js";
import { addAllConfiguredLayers } from "./layers.js";
import { buildSidebar } from "./sidebar.js";
import { toggleCompare } from "./compare.js";

export function createMainMap() {
  const cfg = state.CONFIG.map;

  state.map = new maplibregl.Map({
    container: "map",
    style: buildBaseStyle(cfg),
    center: cfg.center,
    zoom: cfg.zoom,
    pitch: cfg.pitch,
    bearing: cfg.bearing,
    antialias: true,
  });
  const map = state.map;

  map.addControl(new maplibregl.NavigationControl(), "top-right");
  map.addControl(new maplibregl.ScaleControl(), "bottom-left");
  map.addControl(new maplibregl.FullscreenControl(), "top-right");

  map.on("load", async () => {
    map.setTerrain({ source: "terrainSource", exaggeration: cfg.terrain.exaggeration });

    if (cfg.bounds) {
      map.fitBounds(cfg.bounds, { padding: 40, duration: 0, pitch: cfg.pitch, bearing: cfg.bearing });
    }

    await loadIcons(cfg.icons || {});
    addAllConfiguredLayers();
    buildSidebar();
  });
}

function buildBaseStyle(cfg) {
  return {
    version: 8,
    glyphs: "https://fonts.openmaptiles.org/{fontstack}/{range}.pbf",
    sources: {
      basemap: {
        type: "raster",
        tiles: cfg.basemap.tiles,
        tileSize: cfg.basemap.tileSize,
        attribution: cfg.basemap.attribution,
      },
      terrainSource: {
        type: "raster-dem",
        tiles: cfg.terrain.tiles,
        encoding: cfg.terrain.encoding,
        tileSize: cfg.terrain.tileSize,
        maxzoom: cfg.terrain.maxzoom,
        attribution: cfg.terrain.attribution,
      },
    },
    layers: [{ id: "basemap", type: "raster", source: "basemap" }],
  };
}

export function wireTopbarButtons() {
  document.getElementById("btn-terrain3d").addEventListener("click", toggle3D);
  document.getElementById("btn-terrain3d").classList.add("active"); // default view starts in 3D
  document.getElementById("btn-compare").addEventListener("click", toggleCompare);
  document.getElementById("btn-sidebar-toggle").addEventListener("click", () => {
    document.getElementById("sidebar").classList.toggle("collapsed");
  });
}

function toggle3D() {
  state.is3D = !state.is3D;
  const btn = document.getElementById("btn-terrain3d");
  btn.classList.toggle("active", state.is3D);

  if (state.is3D) {
    const t = state.CONFIG.map.terrain3d;
    state.map.setTerrain({ source: "terrainSource", exaggeration: state.CONFIG.map.terrain.exaggeration });
    state.map.easeTo({ pitch: t.pitch, bearing: t.bearing, duration: 800 });
  } else {
    state.map.setTerrain(null);
    state.map.easeTo({ pitch: 0, bearing: 0, duration: 800 });
  }
}
