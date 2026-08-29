// Popup content building + hover/click wiring, plus the always-open "highlight" callouts.
import { state } from "./state.js";
import { noCache, normalizeGeoJSON, fieldLabel, geometryAnchor } from "./utils.js";

// renders a small key/value table instead of one long joined string.
export function buildPopupContent(layer, props) {
  const fields = layer.popupFields || (layer.labelField ? [layer.labelField] : []);
  const table = document.createElement("table");
  table.className = "popup-kv";
  fields.forEach((f) => {
    const val = props[f];
    if (val === undefined || val === null || val === "") return;
    const row = table.insertRow();
    const k = row.insertCell();
    k.className = "popup-kv-key";
    k.textContent = fieldLabel(layer, f);
    const v = row.insertCell();
    v.className = "popup-kv-val";
    v.textContent = val;
  });
  if (!table.rows.length) {
    const div = document.createElement("div");
    div.textContent = "(no data)";
    return div;
  }
  return table;
}

// default trigger is "hover" (transient tooltip that follows mouseenter/mouseleave);
// set layer.popupTrigger = "click" in config for a dismissible popup that only
// appears when the user actually clicks the feature.
export function attachPopup(layer) {
  const map = state.map;
  if (!layer.labelField && !layer.popupFields) return;
  if (state.listenersAttached.has(layer.id)) return; // avoid duplicate handlers on toggle off/on
  state.listenersAttached.add(layer.id);

  map.on("mouseenter", layer.id, () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", layer.id, () => (map.getCanvas().style.cursor = ""));

  if (layer.popupTrigger === "click") {
    map.on("click", layer.id, (e) => {
      new maplibregl.Popup({ closeButton: true, closeOnClick: true })
        .setLngLat(e.lngLat)
        .setDOMContent(buildPopupContent(layer, e.features[0].properties))
        .addTo(map);
    });
  } else {
    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });
    map.on("mouseenter", layer.id, (e) => {
      popup.setLngLat(e.lngLat).setDOMContent(buildPopupContent(layer, e.features[0].properties)).addTo(map);
    });
    map.on("mouseleave", layer.id, () => popup.remove());
  }
}

export function attachVideoPopup(layer) {
  const map = state.map;
  if (state.listenersAttached.has(layer.id)) return;
  state.listenersAttached.add(layer.id);
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
// Uses geometryAnchor() rather than assuming Point geometry, since a highlighted
// feature can just as well be a digitized Polygon (e.g. a landslide extent).
export async function showHighlightPopups(layer) {
  state.autoPopups[layer.id] = [];
  const geojson = normalizeGeoJSON(await fetch(noCache(layer.data)).then((r) => r.json()));
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
        .setLngLat(geometryAnchor(f.geometry))
        .setDOMContent(container)
        .addTo(state.map);
      state.autoPopups[layer.id].push(popup);
    });
}
