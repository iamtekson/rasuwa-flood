// SVG icons are loaded as plain <img> elements, then registered with MapLibre.
import { state } from "./state.js";
import { noCache } from "./utils.js";

// an icon entry is either a plain URL string (rendered as-is, full color), or
// {url, sdf: true} for a solid-silhouette icon whose color is set per-feature
// at render time via the layer's "iconColor" paint option.
export function loadIcons(iconMap) {
  return Promise.all(
    Object.keys(iconMap).map((id) => {
      const spec = iconMap[id];
      const url = typeof spec === "string" ? spec : spec.url;
      const sdf = typeof spec === "object" && !!spec.sdf;
      return loadOneIcon(id, url, sdf);
    })
  );
}

function loadOneIcon(id, url, sdf) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      if (!state.map.hasImage(id)) state.map.addImage(id, img, sdf ? { sdf: true } : {});
      resolve();
    };
    img.onerror = () => resolve(); // don't block the whole app on one bad icon
    img.src = noCache(url);
  });
}
