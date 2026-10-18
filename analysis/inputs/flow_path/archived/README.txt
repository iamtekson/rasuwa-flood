Rasuwa flood: flow path used for "distance from source"

flow_path.geojson / .shp           River centreline, source to Chanauli, 237.1 km, one line.
flow_path_km_ticks.geojson / .shp  A point every 1 km along it; attribute `km`.

km 0 is the flood source at 85.5122 E, 28.2931 N. Distances are lengths along this line
in WGS 84 / UTM 45N (EPSG:32645). The shapefiles are already in EPSG:32645, so measuring along the
line in GIS gives the same km; the GeoJSON files are in EPSG:4326. To place a feature, take the
km of its nearest point on the line (e.g. QGIS "Locate points along lines" or ArcGIS "Locate
Features Along Routes"), or use the nearest tick point.

Reference points:
    11.5 km  Seqiong Village
    14.6 km  Labi Village
    22.0 km  Rasuwagadhi (Rashuwa)
    25.7 km  Timure
    37.6 km  Syabrubesi
    58.1 km  Ghale Gaun
    68.0 km  Betrawati
    76.1 km  Trishuli Bazaar
    79.5 km  Bidur
    85.7 km  Devighat
   126.5 km  Malekhu
   166.6 km  Mugling (approx.)
   199.2 km  Devpur
   204.9 km  Bharatpur
   222.1 km  Chanauli

The damage-profile figure covers km 0-170.
