// Generic add/remove logic for every layer type declared in config/layers.json,
// plus the spotlight-mask effect that can be attached to any "fill" layer.
import { state } from "./state.js";
import { noCache, normalizeGeoJSON, resolveColorExpr, ringSignedArea, windOppositeToOuter } from "./utils.js";
import { attachPopup, attachVideoPopup, showHighlightPopups } from "./popups.js";

// creates the source immediately (empty) so addLayer() can reference it synchronously,
// then fetches + normalizes + fills in the real data once it arrives.
// tolerance: 0 disables geojson-vt's default simplification — our datasets are all
// small, and without this a thin/small polygon (e.g. a narrow landslide runout) can
// get simplified down to a near-zero-area sliver and effectively vanish at low zoom.
function addGeoJsonSourceAsync(id, url) {
  state.map.addSource(id, { type: "geojson", tolerance: 0, data: { type: "FeatureCollection", features: [] } });
  fetch(noCache(url))
    .then((r) => r.json())
    .then((gj) => {
      const src = state.map.getSource(id);
      if (src) src.setData(normalizeGeoJSON(gj));
    })
    .catch((err) => console.error("Failed to load geojson:", url, err));
}

export function addAllConfiguredLayers() {
  const map = state.map;
  state.CONFIG.categories.forEach((cat) => {
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

export function addLayer(layer) {
  const map = state.map;
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
      addGeoJsonSourceAsync(layer.id, layer.data);
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

    case "line": {
      addGeoJsonSourceAsync(layer.id, layer.data);
      const linePaint = {
        "line-color": layer.paint.lineColor,
        "line-width": layer.paint.lineWidth || 2,
      };
      // MapLibre's style validator rejects a paint key that's present but set to
      // undefined (throws instead of treating it as absent) — so only add this key
      // when a real value exists, rather than "value || undefined".
      if (layer.paint.lineDasharray) linePaint["line-dasharray"] = layer.paint.lineDasharray;
      map.addLayer({ id: layer.id, type: "line", source: layer.id, paint: linePaint });
      break;
    }

    case "circle":
      addGeoJsonSourceAsync(layer.id, layer.data);
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
      addGeoJsonSourceAsync(layer.id, layer.data);
      // symbol layers can only place markers on Point geometry — restrict explicitly
      // so a mixed-geometry source (e.g. points + a digitized polygon) doesn't
      // silently try and fail to place a symbol on the polygon.
      map.addLayer({
        id: layer.id,
        type: "symbol",
        source: layer.id,
        filter: ["==", ["geometry-type"], "Point"],
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
          // only takes effect on an SDF icon (config.map.icons[...].sdf: true);
          // ignored harmlessly by full-color icons.
          "icon-color": layer.iconColor ? resolveColorExpr(layer.iconColor) : "#000000",
        },
      });
      // an "icon" layer can also carry Polygon features on the same source (e.g. a
      // digitized landslide/flood-source area alongside point markers) — render
      // those as an actual filled area instead of trying to force a point icon on them.
      if (layer.polygonPaint) {
        const pp = layer.polygonPaint;
        // fillColor/lineColor can be a flat hex string, or a {field, values, default}
        // match-spec (same shape as circleColor/iconColor) to color polygons by a
        // property — e.g. a landslide scar vs. a lake should read as different hazards.
        const fillColorExpr = resolveColorExpr(pp.fillColor);
        const lineColorExpr = pp.lineColor ? resolveColorExpr(pp.lineColor) : fillColorExpr;
        map.addLayer({
          id: layer.id + "-polygon",
          type: "fill",
          source: layer.id,
          filter: ["==", ["geometry-type"], "Polygon"],
          paint: {
            "fill-color": fillColorExpr,
            "fill-opacity": pp.fillOpacity != null ? pp.fillOpacity : 0.35,
          },
        });
        map.addLayer({
          id: layer.id + "-polygon-outline",
          type: "line",
          source: layer.id,
          filter: ["==", ["geometry-type"], "Polygon"],
          paint: {
            "line-color": lineColorExpr,
            "line-width": pp.lineWidth || 1.5,
          },
        });
      }
      break;
  }

  if (layer.type !== "raster" && !layer.alwaysLabel) attachPopup(layer);
  if (layer.type === "icon" && layer.icon === "video_play") attachVideoPopup(layer);
  if (layer.autoPopupOnHighlight) showHighlightPopups(layer);
}

export function removeLayer(layer) {
  const map = state.map;
  const idsToRemove = [layer.id, layer.id + "-outline", layer.id + "-label", layer.id + "-polygon", layer.id + "-polygon-outline"];
  idsToRemove.forEach((id) => {
    if (map.getLayer(id)) map.removeLayer(id);
  });
  if (map.getSource(layer.id)) map.removeSource(layer.id);

  if (state.autoPopups[layer.id]) {
    state.autoPopups[layer.id].forEach((p) => p.remove());
    delete state.autoPopups[layer.id];
  }

  if (layer.spotlight) removeSpotlightMask();
}

// a text-only symbol layer riding on the same source, for circle-type layers that want permanent labels
function addAlwaysOnLabelLayer(layer) {
  state.map.addLayer({
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

// ---------- Spotlight mask: darken everything outside a set of polygons ----------
// Builds one big rectangle covering the map bounds, with a hole punched out for
// every polygon in `layer.data`, and renders it as a dark fill between the raster
// imagery and the vector overlays — so only the chosen area reads "bright".

async function addSpotlightMask(layer) {
  const map = state.map;
  const spec = layer.spotlight === true ? {} : layer.spotlight;
  const color = spec.color || "#000000";
  const opacity = spec.opacity != null ? spec.opacity : 0.55;
  const pad = spec.padDegrees != null ? spec.padDegrees : 2;

  const b = state.CONFIG.map.bounds;
  const outerRing = [
    [b[0][0] - pad, b[0][1] - pad],
    [b[1][0] + pad, b[0][1] - pad],
    [b[1][0] + pad, b[1][1] + pad],
    [b[0][0] - pad, b[1][1] + pad],
    [b[0][0] - pad, b[0][1] - pad],
  ];
  const outerSign = ringSignedArea(outerRing);

  const geojson = normalizeGeoJSON(await fetch(noCache(layer.data)).then((r) => r.json()));
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
  const map = state.map;
  if (map.getLayer("spotlight-mask")) map.removeLayer("spotlight-mask");
  if (map.getSource("spotlight-mask")) map.removeSource("spotlight-mask");
}
