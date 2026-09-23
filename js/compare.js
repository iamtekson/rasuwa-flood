// Before/after imagery swipe: two independent MapLibre maps synced by mapbox-gl-compare.
// Each side shows its own imagery, with the main map's currently-visible vector
// overlays (flood extent, boundaries, points, ...) mirrored on top.
import { state } from "./state.js";
import { loadIcons } from "./icons.js";

const IMAGERY_LAYER_ID = "img";
const iconsReady = new WeakMap(); // compare map -> promise resolved once its icons are registered

export function toggleCompare() {
  const container = document.getElementById("compare-container");
  const mapDiv = document.getElementById("map");
  const btn = document.getElementById("btn-compare");
  const showing = container.classList.contains("hidden");

  if (showing) {
    if (!state.compareInitialized) initCompareMaps();
    container.classList.remove("hidden");
    mapDiv.style.visibility = "hidden";
    btn.classList.add("active");
    const c = state.map.getCenter();
    state.beforeMap.jumpTo({ center: c, zoom: state.map.getZoom(), bearing: 0, pitch: 0 });
    state.afterMap.jumpTo({ center: c, zoom: state.map.getZoom(), bearing: 0, pitch: 0 });
    // re-mirror every time compare opens, so layers toggled in the sidebar since
    // the last open show up (or disappear) on both sides too.
    syncVectorOverlays(state.beforeMap);
    syncVectorOverlays(state.afterMap);
    setTimeout(() => {
      state.beforeMap.resize();
      state.afterMap.resize();
    }, 50);
  } else {
    container.classList.add("hidden");
    mapDiv.style.visibility = "visible";
    btn.classList.remove("active");
  }
}

function initCompareMaps() {
  const imageryCat = state.CONFIG.categories.find((c) => c.id === "imagery");
  const preLayer = imageryCat.layers.find((l) => l.id === "pre_imagery");
  const postLayer = imageryCat.layers.find((l) => l.id === "post_imagery_s2");

  state.beforeMap = new maplibregl.Map({
    container: "before-map",
    style: rasterOnlyStyle(preLayer),
    center: state.CONFIG.map.center,
    zoom: state.CONFIG.map.zoom,
  });
  state.afterMap = new maplibregl.Map({
    container: "after-map",
    style: rasterOnlyStyle(postLayer),
    center: state.CONFIG.map.center,
    zoom: state.CONFIG.map.zoom,
  });
  [state.beforeMap, state.afterMap].forEach((m) =>
    iconsReady.set(m, new Promise((resolve) => m.once("load", () => loadIcons(state.CONFIG.map.icons || {}, m).then(resolve))))
  );

  state.compareControl = new mapboxgl.Compare(state.beforeMap, state.afterMap, "#compare-container", {});
  state.compareInitialized = true;
}

// Copies every layer stacked above the main map's "vector-overlay-anchor" (i.e.
// all active vector layers, in the same z-order, see addAllConfiguredLayers) onto
// the target compare map, above its imagery. The spotlight mask sits below the
// anchor and is deliberately left out — it would darken the imagery being compared.
async function syncVectorOverlays(target) {
  // resolves after the map's "load" and its icons are registered (symbol layers need them)
  await iconsReady.get(target);
  const main = state.map;
  const mainLayers = main.getStyle().layers;
  const anchorIdx = mainLayers.findIndex((l) => l.id === "vector-overlay-anchor");
  const overlays = anchorIdx >= 0 ? mainLayers.slice(anchorIdx + 1) : [];

  // clear the previous mirror (everything except the imagery itself)
  target.getStyle().layers.forEach((l) => {
    if (l.id !== IMAGERY_LAYER_ID) target.removeLayer(l.id);
  });
  Object.keys(target.getStyle().sources).forEach((id) => {
    if (id !== IMAGERY_LAYER_ID) target.removeSource(id);
  });

  // geojson data is fetched asynchronously on the main map, so read it back via
  // getData() rather than from the serialized style.
  const sourceIds = [...new Set(overlays.map((l) => l.source).filter(Boolean))];
  const sources = await Promise.all(
    sourceIds.map(async (id) => {
      const src = main.getSource(id);
      const data = src && src.type === "geojson" ? await src.getData() : null;
      return [id, data];
    })
  );
  sources.forEach(([id, data]) => {
    if (data && !target.getSource(id)) target.addSource(id, { type: "geojson", tolerance: 0, data });
  });

  overlays.forEach((l) => {
    if (l.source && !target.getSource(l.source)) return; // non-geojson source — skip
    if (!target.getLayer(l.id)) target.addLayer(l);
  });
}

function rasterOnlyStyle(layer) {
  return {
    version: 8,
    glyphs: "https://fonts.openmaptiles.org/{fontstack}/{range}.pbf", // for mirrored label layers
    sources: {
      [IMAGERY_LAYER_ID]: {
        type: "raster",
        tiles: layer.tiles,
        tileSize: layer.tileSize || 256,
        attribution: layer.attribution || "",
      },
    },
    layers: [{ id: IMAGERY_LAYER_ID, type: "raster", source: IMAGERY_LAYER_ID }],
  };
}
