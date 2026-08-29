// Builds the layer-toggle sidebar from config/layers.json.
import { state } from "./state.js";
import { swatchColor } from "./utils.js";
import { addLayer, removeLayer } from "./layers.js";
import { showLayerStats } from "./stats.js";

export function buildSidebar() {
  const root = document.getElementById("layer-categories");
  root.innerHTML = "";

  state.CONFIG.categories.forEach((cat) => {
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

      if (layer.data) {
        const statsBtn = document.createElement("button");
        statsBtn.className = "stats-btn";
        statsBtn.textContent = "\u{1F4CA}"; // 📊
        statsBtn.title = "View layer statistics";
        statsBtn.addEventListener("click", (e) => {
          e.preventDefault();
          showLayerStats(layer);
        });
        row.appendChild(statsBtn);
      }

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
}
