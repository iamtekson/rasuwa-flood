# Damage analysis and manuscript figure

Builds panel (b) of the manuscript's damage figure (damage against distance from the flood source) and the GIS layers for the map panels.

## Folders

| Folder | Contents |
| --- | --- |
| `inputs/` | Analysis-specific inputs: the flow path line (`flow_path/flow_path_line.shp`, from colleagues; the previous line is in `flow_path/archived/`), the frozen HOT bridge snapshot, and the map-inset frames (`inset_frames.geojson`) |
| `scripts/` | The Python scripts (below) |
| `intermediate/` | Layers and tables derived by `build_intermediate.py`; safe to delete and rebuild |
| `outputs/` | The figure (`damage_profile.*`) and the dataset comparison (`comparison/`) |

Repo-wide damage layers are read in place from `data/` (paths are listed in `scripts/common.py`).

## Run

From the repo root, with [uv](https://docs.astral.sh/uv/) (each script declares its own dependencies):

```sh
uv run analysis/scripts/build_intermediate.py   # 1. derive layers and tables -> intermediate/
uv run analysis/scripts/damage_profile.py       # 2. draw the figure          -> outputs/damage_profile.png/.pdf/.svg
uv run analysis/scripts/compare_datasets.py     # optional: IIT vs portal     -> outputs/comparison/
```

Without uv: `pip install -r analysis/requirements.txt`, then `python analysis/scripts/<script>.py`.

| Script | Option | Effect |
| --- | --- | --- |
| `build_intermediate.py` | `--near-m 50` | Width of the road band just outside the flood inundation (default 100 m) |
| | `--dedupe-m 3` | Drop IIT buildings with no ID within 3 m of an ID'd building (likely duplicates) |
| `damage_profile.py` | `--utc` | Flood arrival times in UTC (default Nepal Time, UTC+05:45) |
| | `--no-near` | Only road inside the flood inundation |
| | `--no-insets` | No shaded inset bands |
| | `--hp-labels` | Name each hydropower marker (add `--full-hp-names` for untouched names) |
| | `--bin 10`, `--xmax 170` | Bin width and last km shown (defaults 5 and 165) |

## Decisions

- **Distance from source.** Length along `inputs/flow_path/flow_path_line.shp` (EPSG:32645, 194.7 km) from its upstream end. Rasuwagadhi is at km 20.7, Betrawati 65.6, Bidur 77.1 and Mugling 161.8. `intermediate/flow_path/` has the line as GeoJSON and a point every 1 km.
- **Elevation.** Sampled every 50 m along the flow path from `data/tiff/dem_2km_buffer.tif`, smoothed with a 5-point rolling median.
- **Towns and arrival times.** From `data/cities.geojson`. Times are Nepal Time (UTC+05:45); only the towns with a recorded time show one.
- **Flood inundation.** The Shashi & Ashim polygon (`data/Impact-Assessment-Shashi-Ashim/Inundation`, 42.1 km² after repairing its invalid geometry).
- **Buildings.** IIT footprint points: footprints that intersect the flood inundation.
- **Roads.** The OSM network comes in three non-overlapping files (`Road_damaged`, `Road_endangered`, `Complete Road`). Combined, then clipped to the flood inundation, and to a band of `--near-m` just outside it. "Highways & main roads" = OSM `highway` trunk, primary, secondary, tertiary; everything else is "local roads & tracks".
- **Bridges.** The IIT list (107; its 15 status spellings mapped to four classes) plus 11 HOT bridges with no IIT bridge within 100 m; HOT status fills IIT "No info". Destroyed = washed away; damaged = sustained damage and may need repair.
- **Hydropower.** The OSM working-group layer plus Upper Trishuli-2 from the IIT report: 13 mapped structures, one marker each. Trishuli has two because its dam and powerhouse are mapped separately; Upper Trishuli-3A has two polygons with the same name.
- **Inset bands c–e.** The km range of the flow path inside each frame in `inputs/inset_frames.geojson`. Use the same file in QGIS for the shaded areas on the overview map (a); edit the frames there and rebuild, and the bands follow. Delete the file to get the default frames back (each a box around its stretch of river, widened to a 0.85 width-to-height ratio so panels c–e sit in one row).
