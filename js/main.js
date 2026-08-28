// Bhotekoshi Flood Map - main application logic
// Plain vanilla JS + MapLibre GL JS. Layers are driven entirely by config/layers.json.

let CONFIG = null;
let map = null;
let is3D = true; // default view starts pitched (see config.map.pitch)
let compareInitialized = false;
let beforeMap = null;
let afterMap = null;
let compareControl = null;

const listenersAttached = new Set(); // layer ids that already have hover/click handlers bound
const autoPopups = {}; // layer.id -> [maplibregl.Popup, ...] currently shown for highlighted features

const CATEGORY_COLORS_FALLBACK = "#888";

// local data/config files get hand-edited while the map is open — always bypass
// the browser cache for them so a reload reliably shows the latest content.
function noCache(url) {
  return url + (url.includes("?") ? "&" : "?") + "_ts=" + Date.now();
}

init();

async function init() {
  CONFIG = await fetch(noCache("config/layers.json")).then((r) => r.json());
  createMainMap();
  wireTopbarButtons();
}

// ---------- Main map ----------

function createMainMap() {
  const cfg = CONFIG.map;

  map = new maplibregl.Map({
    container: "map",
    style: buildBaseStyle(cfg),
    center: cfg.center,
    zoom: cfg.zoom,
    pitch: cfg.pitch,
    bearing: cfg.bearing,
    antialias: true,
  });

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

// ---------- Icons (SVG files rasterized client-side, then registered with MapLibre) ----------

function loadIcons(iconMap) {
  const ids = Object.keys(iconMap);
  return Promise.all(ids.map((id) => loadOneIcon(id, iconMap[id])));
}

function loadOneIcon(id, url) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      if (!map.hasImage(id)) map.addImage(id, img);
      resolve();
    };
    img.onerror = () => resolve(); // don't block the whole app on one bad icon
    img.src = noCache(url);
  });
}

// ---------- Layer add/remove (generic, driven by layers.json "type") ----------

function addAllConfiguredLayers() {
  CONFIG.categories.forEach((cat) => {
    cat.layers.forEach((layer) => {
      if (layer.active) addLayer(layer);
    });
    // fixed z-order anchor: everything vector (flood extent, boundaries, points, ...)
    // gets added after this point and so stacks above it; raster/imagery layers and
    // the spotlight mask are explicitly inserted below it via beforeId.
    if (cat.id === "imagery" && !map.getLayer("vector-overlay-anchor")) {
      map.addLayer({ id: "vector-overlay-anchor", type: "background", paint: { "background-opacity": 0 } });
    }
  });
}

function addLayer(layer) {
  if (map.getLayer(layer.id)) return; // already added

  switch (layer.type) {
    case "raster":
      map.addSource(layer.id, {
        type: "raster",
        tiles: layer.tiles,
        tileSize: layer.tileSize || 256,
        attribution: layer.attribution || "",
      });
      // always insert below the anchor, even if this raster is toggled on after
      // vector layers already exist, so imagery never ends up on top of them.
      map.addLayer(
        { id: layer.id, type: "raster", source: layer.id },
        map.getLayer("vector-overlay-anchor") ? "vector-overlay-anchor" : undefined
      );
      break;

    case "fill":
      map.addSource(layer.id, { type: "geojson", data: noCache(layer.data) });
      map.addLayer({
        id: layer.id,
        type: "fill",
        source: layer.id,
        minzoom: layer.minzoom || 0,
        paint: {
          "fill-color": layer.paint.fillColor,
          "fill-opacity": layer.paint.fillOpacity,
        },
      });
      map.addLayer({
        id: layer.id + "-outline",
        type: "line",
        source: layer.id,
        minzoom: layer.minzoom || 0,
        paint: {
          "line-color": layer.paint.lineColor,
          "line-width": layer.paint.lineWidth || 1,
        },
      });
      if (layer.spotlight) addSpotlightMask(layer);
      break;

    case "line":
      map.addSource(layer.id, { type: "geojson", data: noCache(layer.data) });
      map.addLayer({
        id: layer.id,
        type: "line",
        source: layer.id,
        paint: {
          "line-color": layer.paint.lineColor,
          "line-width": layer.paint.lineWidth || 2,
          "line-dasharray": layer.paint.lineDasharray || undefined,
        },
      });
      break;

    case "circle":
      map.addSource(layer.id, { type: "geojson", data: noCache(layer.data) });
      map.addLayer({
        id: layer.id,
        type: "circle",
        source: layer.id,
        paint: {
          "circle-color": resolveColorExpr(layer.paint.circleColor),
          "circle-radius": layer.paint.circleRadius || 5,
          "circle-stroke-color": layer.paint.circleStrokeColor || "#fff",
          "circle-stroke-width": layer.paint.circleStrokeWidth || 1,
        },
      });
      if (layer.alwaysLabel && layer.labelField) addAlwaysOnLabelLayer(layer);
      break;

    case "icon":
      map.addSource(layer.id, { type: "geojson", data: noCache(layer.data) });
      map.addLayer({
        id: layer.id,
        type: "symbol",
        source: layer.id,
        layout: {
          "icon-image": layer.iconField ? ["get", layer.iconField] : layer.icon,
          "icon-size": layer.iconSize || 0.5,
          "icon-allow-overlap": true,
          "text-field": layer.alwaysLabel && layer.labelField ? ["get", layer.labelField] : "",
          "text-font": ["Noto Sans Regular"],
          "text-size": 12,
          "text-anchor": "top",
          "text-offset": [0, 1.1],
          "text-allow-overlap": !!layer.alwaysLabel,
          "text-optional": true,
        },
        paint: {
          "text-color": "#ffffff",
          "text-halo-color": "#111111",
          "text-halo-width": 1.4,
        },
      });
      break;
  }

  if (layer.type !== "raster" && !layer.alwaysLabel) attachPopup(layer);
  if (layer.type === "icon" && layer.icon === "video_play") attachVideoPopup(layer);
  if (layer.autoPopupOnHighlight) showHighlightPopups(layer);
}

function removeLayer(layer) {
  const idsToRemove = [layer.id, layer.id + "-outline", layer.id + "-label"];
  idsToRemove.forEach((id) => {
    if (map.getLayer(id)) map.removeLayer(id);
  });
  if (map.getSource(layer.id)) map.removeSource(layer.id);

  if (autoPopups[layer.id]) {
    autoPopups[layer.id].forEach((p) => p.remove());
    delete autoPopups[layer.id];
  }

  if (layer.spotlight) removeSpotlightMask();
}

// ---------- Spotlight mask: darken everything outside a set of polygons ----------
// Builds one big rectangle covering the map bounds, with a hole punched out for
// every polygon in `layer.data`, and renders it as a dark fill between the raster
// imagery and the vector overlays — so only the chosen area reads "bright".

function ringSignedArea(ring) {
  let sum = 0;
  for (let i = 0; i < ring.length - 1; i++) {
    const [x1, y1] = ring[i];
    const [x2, y2] = ring[i + 1];
    sum += x1 * y2 - x2 * y1;
  }
  return sum;
}

// a hole ring must wind opposite to the outer ring, regardless of the source's
// own winding convention (shapefile exports are often clockwise, GeoJSON expects
// holes counter to whatever the outer ring does) — so just compare signs.
function windOppositeToOuter(ring, outerSign) {
  const sign = Math.sign(ringSignedArea(ring));
  return sign !== 0 && sign === Math.sign(outerSign) ? ring.slice().reverse() : ring;
}

async function addSpotlightMask(layer) {
  const spec = layer.spotlight === true ? {} : layer.spotlight;
  const color = spec.color || "#000000";
  const opacity = spec.opacity != null ? spec.opacity : 0.55;
  const pad = spec.padDegrees != null ? spec.padDegrees : 2;

  const b = CONFIG.map.bounds;
  const outerRing = [
    [b[0][0] - pad, b[0][1] - pad],
    [b[1][0] + pad, b[0][1] - pad],
    [b[1][0] + pad, b[1][1] + pad],
    [b[0][0] - pad, b[1][1] + pad],
    [b[0][0] - pad, b[0][1] - pad],
  ];
  const outerSign = ringSignedArea(outerRing);

  const geojson = await fetch(noCache(layer.data)).then((r) => r.json());
  const holes = [];
  geojson.features.forEach((f) => {
    const g = f.geometry;
    if (!g) return;
    const polys = g.type === "MultiPolygon" ? g.coordinates : g.type === "Polygon" ? [g.coordinates] : [];
    polys.forEach((poly) => holes.push(windOppositeToOuter(poly[0], outerSign)));
  });

  const maskFeature = {
    type: "Feature",
    properties: {},
    geometry: { type: "Polygon", coordinates: [outerRing, ...holes] },
  };

  if (map.getLayer("spotlight-mask")) map.removeLayer("spotlight-mask");
  if (map.getSource("spotlight-mask")) map.removeSource("spotlight-mask");

  map.addSource("spotlight-mask", { type: "geojson", data: maskFeature });
  map.addLayer(
    {
      id: "spotlight-mask",
      type: "fill",
      source: "spotlight-mask",
      paint: { "fill-color": color, "fill-opacity": opacity },
    },
    map.getLayer("vector-overlay-anchor") ? "vector-overlay-anchor" : undefined
  );
}

function removeSpotlightMask() {
  if (map.getLayer("spotlight-mask")) map.removeLayer("spotlight-mask");
  if (map.getSource("spotlight-mask")) map.removeSource("spotlight-mask");
}

// a text-only symbol layer riding on the same source, for circle-type layers that want permanent labels
function addAlwaysOnLabelLayer(layer) {
  map.addLayer({
    id: layer.id + "-label",
    type: "symbol",
    source: layer.id,
    layout: {
      "text-field": ["get", layer.labelField],
      "text-font": ["Noto Sans Regular"],
      "text-size": 12,
      "text-anchor": "top",
      "text-offset": [0, 0.8],
      "text-allow-overlap": true,
      "text-optional": true,
    },
    paint: {
      "text-color": "#ffffff",
      "text-halo-color": "#111111",
      "text-halo-width": 1.4,
    },
  });
}

// paint.circleColor is either a flat color string, or an object
// { field, values: {value: color}, default } which becomes a "match" expression.
function resolveColorExpr(spec) {
  if (typeof spec === "string") return spec;
  const expr = ["match", ["get", spec.field]];
  Object.keys(spec.values).forEach((k) => {
    expr.push(k, spec.values[k]);
  });
  expr.push(spec.default || "#888888");
  return expr;
}

// swatches need a single CSS color; for a {field, values, default} spec, just show its default.
function flatColor(spec) {
  if (typeof spec === "string") return spec;
  return spec.default || "#888888";
}

function popupText(layer, props) {
  if (layer.popupFields) {
    return layer.popupFields
      .filter((f) => props[f])
      .map((f) => props[f])
      .join(" — ");
  }
  return props[layer.labelField] || "(unnamed)";
}

// default trigger is "hover" (transient tooltip that follows mouseenter/mouseleave);
// set layer.popupTrigger = "click" in config for a dismissible popup that only
// appears when the user actually clicks the feature.
function attachPopup(layer) {
  if (!layer.labelField && !layer.popupFields) return;
  if (listenersAttached.has(layer.id)) return; // avoid duplicate handlers on toggle off/on
  listenersAttached.add(layer.id);

  map.on("mouseenter", layer.id, () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", layer.id, () => (map.getCanvas().style.cursor = ""));

  if (layer.popupTrigger === "click") {
    map.on("click", layer.id, (e) => {
      const text = popupText(layer, e.features[0].properties);
      new maplibregl.Popup({ closeButton: true, closeOnClick: true })
        .setLngLat(e.lngLat)
        .setText(text || "(no data)")
        .addTo(map);
    });
  } else {
    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });
    map.on("mouseenter", layer.id, (e) => {
      const text = popupText(layer, e.features[0].properties);
      popup.setLngLat(e.lngLat).setText(text || "(no data)").addTo(map);
    });
    map.on("mouseleave", layer.id, () => popup.remove());
  }
}

function attachVideoPopup(layer) {
  if (listenersAttached.has(layer.id)) return;
  listenersAttached.add(layer.id);
  map.on("mouseenter", layer.id, () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", layer.id, () => (map.getCanvas().style.cursor = ""));

  map.on("click", layer.id, (e) => {
    const props = e.features[0].properties;
    const title = props[layer.labelField] || props.title || "Eyewitness video";
    const videoUrl = props.video_url;

    const container = document.createElement("div");
    const titleEl = document.createElement("div");
    titleEl.className = "video-popup-title";
    titleEl.textContent = title;
    container.appendChild(titleEl);

    if (videoUrl) {
      const video = document.createElement("video");
      video.controls = true;
      video.style.maxWidth = "280px";
      video.style.maxHeight = "200px";
      video.style.display = "block";
      video.src = videoUrl;
      container.appendChild(video);
    } else {
      const note = document.createElement("div");
      note.className = "video-popup-note";
      note.textContent = "No video URL yet — placeholder point. See " + (props.source_page || "source");
      container.appendChild(note);
    }

    new maplibregl.Popup({ closeButton: true, maxWidth: "320px" })
      .setLngLat(e.lngLat)
      .setDOMContent(container)
      .addTo(map);
  });
}

// for layers where individual features are flagged properties.highlight === true,
// show a permanently-open (dismissible) callout popup on load, matching the
// "auto open popup" reference behaviour for things like the flood-origin point.
async function showHighlightPopups(layer) {
  autoPopups[layer.id] = [];
  const geojson = await fetch(noCache(layer.data)).then((r) => r.json());
  geojson.features
    .filter((f) => f.properties && f.properties.highlight)
    .forEach((f) => {
      const props = f.properties;
      const container = document.createElement("div");
      container.className = "callout-content";
      const title = document.createElement("div");
      title.className = "callout-title";
      title.textContent = props[layer.labelField] || props.name || "Highlighted location";
      container.appendChild(title);
      if (props.note) {
        const note = document.createElement("div");
        note.className = "callout-note";
        note.textContent = props.note;
        container.appendChild(note);
      }
      const popup = new maplibregl.Popup({
        closeButton: true,
        closeOnClick: false,
        className: "callout-popup",
        maxWidth: "240px",
      })
        .setLngLat(f.geometry.coordinates)
        .setDOMContent(container)
        .addTo(map);
      autoPopups[layer.id].push(popup);
    });
}

// ---------- Sidebar (built from layers.json) ----------

function buildSidebar() {
  const root = document.getElementById("layer-categories");
  root.innerHTML = "";

  CONFIG.categories.forEach((cat) => {
    const catEl = document.createElement("div");
    catEl.className = "layer-category";

    const h2 = document.createElement("h2");
    h2.textContent = cat.label;
    catEl.appendChild(h2);

    cat.layers.forEach((layer) => {
      const row = document.createElement("div");
      row.className = "layer-row";

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.id = "chk-" + layer.id;
      checkbox.checked = !!layer.active;
      checkbox.addEventListener("change", () => {
        layer.active = checkbox.checked;
        if (checkbox.checked) addLayer(layer);
        else removeLayer(layer);
      });

      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = swatchColor(layer);

      const label = document.createElement("label");
      label.htmlFor = checkbox.id;
      label.textContent = layer.label;

      row.appendChild(checkbox);
      row.appendChild(swatch);
      row.appendChild(label);
      catEl.appendChild(row);

      if (layer.note) {
        const note = document.createElement("p");
        note.className = "layer-note";
        note.textContent = layer.note;
        catEl.appendChild(note);
      }
    });

    root.appendChild(catEl);
  });

  buildLegend();
}

function swatchColor(layer) {
  if (layer.type === "raster") return "#555";
  if (layer.type === "icon") return "#555"; // icon swatches would need per-icon rendering; keep neutral
  if (layer.paint && layer.paint.fillColor) return layer.paint.fillColor;
  if (layer.paint && layer.paint.circleColor) return flatColor(layer.paint.circleColor);
  if (layer.paint && layer.paint.lineColor) return layer.paint.lineColor;
  return CATEGORY_COLORS_FALLBACK;
}

function buildLegend() {
  const el = document.getElementById("legend-items");
  el.innerHTML = "";
  CONFIG.categories.forEach((cat) => {
    cat.layers.forEach((layer) => {
      const row = document.createElement("div");
      row.className = "layer-row";
      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = swatchColor(layer);
      const label = document.createElement("label");
      label.textContent = layer.label;
      row.appendChild(swatch);
      row.appendChild(label);
      el.appendChild(row);
    });
  });
}

// ---------- Topbar buttons ----------

function wireTopbarButtons() {
  document.getElementById("btn-terrain3d").addEventListener("click", toggle3D);
  document.getElementById("btn-terrain3d").classList.add("active"); // default view starts in 3D
  document.getElementById("btn-compare").addEventListener("click", toggleCompare);
  document.getElementById("btn-sidebar-toggle").addEventListener("click", () => {
    document.getElementById("sidebar").classList.toggle("collapsed");
  });
}

function toggle3D() {
  is3D = !is3D;
  const btn = document.getElementById("btn-terrain3d");
  btn.classList.toggle("active", is3D);

  if (is3D) {
    const t = CONFIG.map.terrain3d;
    map.setTerrain({ source: "terrainSource", exaggeration: CONFIG.map.terrain.exaggeration });
    map.easeTo({ pitch: t.pitch, bearing: t.bearing, duration: 800 });
  } else {
    map.setTerrain(null);
    map.easeTo({ pitch: 0, bearing: 0, duration: 800 });
  }
}

// ---------- Compare (before/after imagery swipe) ----------

function toggleCompare() {
  const container = document.getElementById("compare-container");
  const mapDiv = document.getElementById("map");
  const btn = document.getElementById("btn-compare");
  const showing = container.classList.contains("hidden");

  if (showing) {
    if (!compareInitialized) initCompareMaps();
    container.classList.remove("hidden");
    mapDiv.style.visibility = "hidden";
    btn.classList.add("active");
    const c = map.getCenter();
    beforeMap.jumpTo({ center: c, zoom: map.getZoom(), bearing: 0, pitch: 0 });
    afterMap.jumpTo({ center: c, zoom: map.getZoom(), bearing: 0, pitch: 0 });
    setTimeout(() => {
      beforeMap.resize();
      afterMap.resize();
    }, 50);
  } else {
    container.classList.add("hidden");
    mapDiv.style.visibility = "visible";
    btn.classList.remove("active");
  }
}

function initCompareMaps() {
  const imageryCat = CONFIG.categories.find((c) => c.id === "imagery");
  const preLayer = imageryCat.layers.find((l) => l.id === "pre_imagery");
  const postLayer = imageryCat.layers.find((l) => l.id === "post_imagery");

  beforeMap = new maplibregl.Map({
    container: "before-map",
    style: rasterOnlyStyle(preLayer),
    center: CONFIG.map.center,
    zoom: CONFIG.map.zoom,
  });
  afterMap = new maplibregl.Map({
    container: "after-map",
    style: rasterOnlyStyle(postLayer),
    center: CONFIG.map.center,
    zoom: CONFIG.map.zoom,
  });

  compareControl = new mapboxgl.Compare(beforeMap, afterMap, "#compare-container", {});
  compareInitialized = true;
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
