// Before/after imagery swipe: two independent MapLibre maps synced by mapbox-gl-compare.
import { state } from "./state.js";

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
  const postLayer = imageryCat.layers.find((l) => l.id === "post_imagery");

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

  state.compareControl = new mapboxgl.Compare(state.beforeMap, state.afterMap, "#compare-container", {});
  state.compareInitialized = true;
}

function rasterOnlyStyle(layer) {
  return {
    version: 8,
    sources: {
      img: {
        type: "raster",
        tiles: layer.tiles,
        tileSize: layer.tileSize || 256,
        attribution: layer.attribution || "",
      },
    },
    layers: [{ id: "img", type: "raster", source: "img" }],
  };
}
