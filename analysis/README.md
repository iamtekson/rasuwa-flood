# Damage analysis and manuscript figure

Scripts that turn the damage layers in `data/` into the manuscript's damage-profile figure, the QGIS helper layers for the map panels, and the IIT vs portal comparison numbers.

## Run

Each script declares its own dependencies, so [uv](https://docs.astral.sh/uv/) runs it with no setup, from the repo root:

```sh
uv run analysis/damage_profile.py     # figure panel (b) -> analysis/output/damage_profile.png/.pdf/.svg
uv run analysis/build_layers.py       # QGIS helper layers + impact_by_km.csv
uv run analysis/compare_datasets.py   # IIT vs portal numbers + comparison_profile.png
```

Without uv: `pip install -r analysis/requirements.txt`, then `python analysis/<script>.py`.

`damage_profile.py` options:

| Option | Effect |
| --- | --- |
| `--no-endangered` | Drop the hatched "within 100 m of flood edge" road segment |
| `--no-insets` | Drop the shaded c/d/e bands (edit `INSETS` at the top of the script to move them) |
| `--dedupe-m 3` | Drop IIT buildings with no ID that sit within 3 m of an ID'd building (likely duplicates) |
| `--hp-labels` | Name each hydropower marker (default: markers only); add `--full-hp-names` for untouched names |
| `--bin 10` | Bin width in km (default 5) |

## Figure decisions

- **Distance axis.** Every layer is placed by its distance from the source along the flow line in `data/elevation_profile.json` (the portal's elevation profile), so Rasuwagadhi is at km 22 and Mugling at about km 167. Those km are lengths in UTM 45N along the full-resolution river line (`merge_river_line()` in `elevation_profile/flood_profile.py`, first 237.1 km); `export_flowpath.py` packages that line for collaborators.
- **Buildings.** IIT footprint points (`data/Impact-Assessment-Shashi-Ashim/Builidngs`), counted per bin. The portal's `buildings_essential.geojson` is capped at 6,000 features and is not used for counts.
- **Roads.** `data/OSM/4. Road Network/Road_damaged.geojson` (road inside the OSM working-group flood extent). "Highways & main roads" = OSM `highway` tags trunk, primary, secondary and tertiary (`MAIN_ROADS` in `common.py`); everything else (unclassified, residential, service, track, path, footway) is "local roads & tracks".
- **Endangered roads.** `Road_endangered.geojson` is road within 0–100 m *outside* the flood extent. It does not overlap the damaged layer (the same OSM ways are split at the flood edge), so it stacks on top as a separate hatched segment.
- **Bridges.** The IIT list (107) with its 15 status spellings mapped to Destroyed / Damaged / Intact / No info, plus 11 HOT bridges with no IIT bridge within 100 m. HOT status fills IIT "No info" where they match. HOT data is read from the frozen snapshot `analysis/data/hot_bridge_damage_2026-10-14.geojson`; delete it to re-download the live layer.
- **Hydropower.** The OSM working-group layer (empty geometries dropped) plus Upper Trishuli-2 from the IIT report: 13 mapped structures, one marker each, unlabelled by default. With `--hp-labels`, labels come from the layer's `Name` field, with the generic words "Hydropower", "Hydroelectric" and "Project" dropped (`--full-hp-names` keeps the names untouched). Trishuli has two markers because the layer maps its dam and powerhouse separately; Upper Trishuli-3A has two polygons with the same name. To change a label, rename the feature in the GeoJSON. Labels are pushed apart to at least `HP_LABEL_GAP_KM` (4.8 km), and each leader rises vertically from its marker before angling to its label.
- **Shaded bands c/d/e.** Placeholders marking where the map insets sit (Rasuwagadhi–Timure, the Upper Trishuli hydropower cluster, Betrawati–Trishuli–Bidur). The dotted line is the China–Nepal border.

## Files

| File | Purpose |
| --- | --- |
| `common.py` | Paths, the flow-path linear reference, bridge harmonisation, hydropower list |
| `damage_profile.py` | Manuscript figure panel (b) |
| `build_layers.py` | `flowpath.geojson`, `flowpath_km_ticks.geojson`, `bridges_harmonised.geojson`, `bridges_hot_only.geojson`, `hydropower.geojson`, `impact_by_km.csv`. `flowpath.geojson` is a thinned display line (900 points); its GIS length is about 3% short, so don't measure along it |
| `export_flowpath.py` | `rasuwa_flow_path.zip`: the full-resolution line the km were measured on (0–237 km, GeoJSON + UTM 45N shapefile), 1 km ticks and a README. Share this one |
| `compare_datasets.py` | Comparison numbers, `comparison_profile.png`, `flood_extent_agreement.geojson` |
| `data/` | Frozen HOT bridge snapshot |
| `output/` | Everything the scripts write; safe to delete and regenerate |
