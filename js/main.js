// Bhotekoshi Flood Map - entry point.
// Plain vanilla JS (ES modules) + MapLibre GL JS. Layers are driven entirely by
// config/layers.json. See js/state.js, layers.js, popups.js, sidebar.js, stats.js,
// compare.js, map-core.js, icons.js, and utils.js for the actual logic.
import { state } from "./state.js";
import { noCache } from "./utils.js";
import { createMainMap, wireTopbarButtons } from "./map-core.js";

init();

async function init() {
  state.CONFIG = await fetch(noCache("config/layers.json")).then((r) => r.json());
  createMainMap();
  wireTopbarButtons();
  window.__debug = state; // console/devtools inspection only, not used by app logic
}
