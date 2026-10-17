"""
Carpathian Bears Movement Analysis (MapLibre + DB-first, CSV-fallback)

Performance upgrades:
- Sidebar uses st.form() -> rerun only on Apply
- st.cache_data() for CSV load + DB queries
- Downsampling: max points per bear (keeps UI responsive)
- Faster GeoJSON building (no iterrows in hot path)

Color upgrade:
- Unique colors per bear in the current dataset/view (no duplicates)
- New bears get a new unused color automatically
"""

import os
import calendar
from datetime import datetime
import colorsys

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

import streamlit.components.v1 as components

from wildlife_db_mariadb import WildlifeDatabase


# =========================
# Saison-Erklaerung
# =========================
# The season values in the Carpathian dataset (column Season2) are NOT
# calendar seasons but biological annual phases of the brown bear. Terms
# such as "Hyperphagia" or "Forest fruits" are not interpretable without
# explanation, so the text is defined once here and used by all three
# filters (map.py, pages/2_Experiments.py and the Carpathian tab) instead
# of being maintained in three places.
#
# The month ranges were measured from the data itself (1_bears_RO.csv,
# 59,997 fixes) and are deliberately given as ranges: the phases depend on
# the behaviour of the individual bear rather than on fixed calendar
# dates, which is why the boundary months overlap.
SEASON_DESCRIPTIONS = {
    "Winter sleep":
        "Winter dormancy (roughly Nov-Mar): the bear stays in the den and "
        "barely changes location.",
    "Den exit and reproduction":
        "Den exit and mating season (roughly Mar-Jun): the bear leaves the "
        "den and ranges widely while searching for a mate.",
    "Forest fruits":
        "Forest fruits (roughly Jun-Aug): berries and fruit ripen and "
        "foraging is concentrated within the forest.",
    "Hyperphagia":
        "Hyperphagia (roughly Aug-Nov): greatly increased food intake to "
        "build fat reserves before dormancy; the most active phase.",
}

SEASON_HELP = (
    "Not calendar seasons but **biological annual phases of the brown "
    "bear**, taken from the Carpathian dataset (column `Season2`):\n\n"
    + "\n".join(f"- **{name}** - {text}" for name, text in SEASON_DESCRIPTIONS.items())
    + "\n\nPurpose of the filter: activity and movement patterns differ "
      "considerably between the phases. Restricting the data to one phase "
      "compares like with like, for example only hyperphagia, during which "
      "bears travel furthest."
)


# =========================
# Paths + CSV fallback
# =========================
def _project_paths():
    app_dir = os.path.dirname(os.path.abspath(__file__))
    csv_dir = os.path.join(app_dir, "data", "animal_data", "carpathian_bears")
    return app_dir, csv_dir


def _try_import_pyproj():
    try:
        from pyproj import Transformer  # type: ignore
        return Transformer
    except Exception:
        return None


def _transform_epsg3844_to_wgs84(df: pd.DataFrame) -> pd.DataFrame:
    Transformer = _try_import_pyproj()
    if Transformer is None:
        st.error(
            "CSV fallback loaded, but 'pyproj' is missing for coordinate transformation.\n\n"
            "Install it with:\n"
            "pip install pyproj"
        )
        return df

    if "x" not in df.columns and "X" in df.columns:
        df["x"] = df["X"]
    if "y" not in df.columns and "Y" in df.columns:
        df["y"] = df["Y"]

    if "x" not in df.columns or "y" not in df.columns:
        st.error("CSV fallback: Could not find x/y columns needed for coordinate transform.")
        return df

    transformer = Transformer.from_crs("EPSG:3844", "EPSG:4326", always_xy=True)
    xs = pd.to_numeric(df["x"], errors="coerce").to_numpy()
    ys = pd.to_numeric(df["y"], errors="coerce").to_numpy()
    lng, lat = transformer.transform(xs, ys)

    df["lng"] = lng
    df["lat"] = lat
    return df


def _normalize_tracking_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    # timestamp naming
    if "timestamp" not in df.columns:
        if "time" in df.columns:
            df = df.rename(columns={"time": "timestamp"})
        elif "datetime" in df.columns:
            df = df.rename(columns={"datetime": "timestamp"})

    # bear_id from Name if missing
    if "bear_id" not in df.columns:
        df["bear_id"] = None
    if "Name" in df.columns:
        df["bear_id"] = df["bear_id"].fillna(df["Name"])
        bad = df["bear_id"].astype(str).str.strip().isin(["", "None", "nan", "NaN"])
        df.loc[bad, "bear_id"] = df["Name"]

    # unify sex/age/season
    if "sex" not in df.columns and "Sex" in df.columns:
        df["sex"] = df["Sex"]
    if "age" not in df.columns and "Age" in df.columns:
        df["age"] = df["Age"]
    if "season" not in df.columns:
        if "Season2" in df.columns:
            df["season"] = df["Season2"]
        elif "Season" in df.columns:
            df["season"] = df["Season"]

    # x/y normalization
    if "x" not in df.columns and "X" in df.columns:
        df["x"] = df["X"]
    if "y" not in df.columns and "Y" in df.columns:
        df["y"] = df["Y"]

    # parse timestamp
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    else:
        df["timestamp"] = pd.NaT

    # Ensure required cols exist
    for col in ["bear_id", "sex", "age", "season", "x", "y"]:
        if col not in df.columns:
            df[col] = None

    # Transform if lat/lng missing
    if "lat" not in df.columns or "lng" not in df.columns:
        df = _transform_epsg3844_to_wgs84(df)

    # Drop invalid lat/lng
    if "lat" in df.columns and "lng" in df.columns:
        df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
        df["lng"] = pd.to_numeric(df["lng"], errors="coerce")
        df = df.dropna(subset=["lat", "lng"])

    df["bear_id"] = df["bear_id"].astype(str)
    for c in ["sex", "age", "season"]:
        if c in df.columns:
            df[c] = df[c].astype(str)

    return df.reset_index(drop=True)


@st.cache_data(show_spinner=False)
def _load_carpathian_csv_tracking_cached() -> pd.DataFrame:
    _, csv_dir = _project_paths()
    f1 = os.path.join(csv_dir, "1_bears_RO.csv")
    f2 = os.path.join(csv_dir, "2_bears_RO_seasons.csv")

    if not os.path.exists(f1):
        return pd.DataFrame()

    df1 = _normalize_tracking_columns(pd.read_csv(f1))

    df2 = pd.DataFrame()
    if os.path.exists(f2):
        try:
            df2 = _normalize_tracking_columns(pd.read_csv(f2))
        except Exception:
            df2 = pd.DataFrame()

    df = pd.concat([df1, df2], ignore_index=True) if not df2.empty else df1.copy()
    if "timestamp" in df.columns:
        df = df.sort_values("timestamp")
    return df.reset_index(drop=True)


def _csv_get_bears_list(tracking_df: pd.DataFrame) -> pd.DataFrame:
    if tracking_df is None or tracking_df.empty:
        return pd.DataFrame(columns=["bear_id", "sex", "age"])
    out = tracking_df[["bear_id", "sex", "age"]].drop_duplicates().copy()
    out["bear_id"] = out["bear_id"].astype(str)
    return out.sort_values("bear_id").reset_index(drop=True)


def _csv_get_distinct_seasons(tracking_df: pd.DataFrame):
    if tracking_df is None or tracking_df.empty or "season" not in tracking_df.columns:
        return []
    seasons = tracking_df["season"].dropna().astype(str).unique().tolist()
    seasons = [s for s in seasons if s.strip() != ""]
    return sorted(seasons)


def _csv_get_date_range(tracking_df: pd.DataFrame):
    if tracking_df is None or tracking_df.empty or "timestamp" not in tracking_df.columns:
        return datetime(2018, 1, 1).date(), datetime(2023, 12, 31).date()
    ts = tracking_df["timestamp"].dropna()
    if ts.empty:
        return datetime(2018, 1, 1).date(), datetime(2023, 12, 31).date()
    return ts.min().date(), ts.max().date()


def _csv_filter_bear_data(tracking_df: pd.DataFrame, bear_id: str, start_dt: datetime, end_dt: datetime, seasons=None):
    if tracking_df is None or tracking_df.empty:
        return pd.DataFrame()

    df = tracking_df[tracking_df["bear_id"].astype(str) == str(bear_id)].copy()
    if "timestamp" in df.columns:
        df = df[(df["timestamp"] >= start_dt) & (df["timestamp"] <= end_dt)]
    if seasons:
        df = df[df["season"].astype(str).isin([str(s) for s in seasons])]
    return df.sort_values("timestamp")


# =========================
# DB (cached wrappers)
# =========================
db = WildlifeDatabase()


@st.cache_data(show_spinner=False, ttl=60)
def _db_get_bears_list_cached():
    try:
        return db.get_bears_list()
    except Exception:
        return pd.DataFrame()


@st.cache_data(show_spinner=False, ttl=300)
def _db_get_seasons_cached():
    try:
        s = db.get_distinct_values("bears_tracking", "season")
        return s or []
    except Exception:
        return []


@st.cache_data(show_spinner=False, ttl=300)
def _db_get_date_range_cached():
    try:
        return db.get_date_range("bears_tracking", "timestamp")
    except Exception:
        return datetime(2018, 1, 1).date(), datetime(2023, 12, 31).date()


@st.cache_data(show_spinner=False, ttl=60)
def _db_get_bear_data_cached(bear_id: str, start_iso: str, end_iso: str, season: str | None):
    start_dt = pd.to_datetime(start_iso)
    end_dt = pd.to_datetime(end_iso)
    try:
        return db.get_bear_data(bear_id=bear_id, start_date=start_dt, end_date=end_dt, season=season)
    except Exception:
        return pd.DataFrame()


# =========================
# Performance: downsampling
# =========================
def _downsample_per_bear(df: pd.DataFrame, max_points_per_bear: int) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    if max_points_per_bear <= 0:
        return df

    out = []
    for bid, g in df.groupby("bear_id"):
        g = g.sort_values("timestamp") if "timestamp" in g.columns else g
        n = len(g)
        if n > max_points_per_bear:
            step = max(1, n // max_points_per_bear)
            g = g.iloc[::step].copy()
        out.append(g)
    return pd.concat(out, ignore_index=True) if out else df


# =========================
# Unique color mapping (NO DUPLICATES)
# =========================
def _rgb_to_hex(r: float, g: float, b: float) -> str:
    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))


def _build_unique_color_map(bear_ids: list[str]) -> dict[str, str]:
    """
    A unique, maximally distinguishable colour per bear_id.

    Instead of hash-based hues, which tend to cluster into many similar
    shades, the hues are distributed EVENLY around the colour wheel by the
    index of the bear. Lightness and saturation alternate in addition, so
    that even neighbouring hues stay clearly distinguishable.

    Deterministic: the same bear_ids always yield the same colours.
    """
    ids = sorted(set([str(x) for x in bear_ids]))
    n = max(1, len(ids))
    out: dict[str, str] = {}

    # Helligkeit/Saettigung im Dreier-Wechsel -> trennt benachbarte Huetones extra
    lightness_levels = [0.50, 0.62, 0.40]
    saturation_levels = [0.85, 0.70, 0.95]

    for i, bid in enumerate(ids):
        hue = (i * 360.0 / n) % 360.0          # gleichmaessig verteilt
        light = lightness_levels[i % len(lightness_levels)]
        sat = saturation_levels[i % len(saturation_levels)]
        r, g, b = colorsys.hls_to_rgb(hue / 360.0, light, sat)
        out[bid] = _rgb_to_hex(r, g, b)

    return out


# =========================
# Daily aggregation
# =========================
def _df_daily_positions(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    d = df.copy()
    d["timestamp"] = pd.to_datetime(d.get("timestamp", pd.NaT), errors="coerce")
    d = d.dropna(subset=["timestamp"])
    d["day"] = d["timestamp"].dt.date

    def _first_non_null(series):
        s = series.dropna()
        if s.empty:
            return ""
        return str(s.iloc[0])

    agg = (
        d.groupby(["bear_id", "day"])
        .agg(
            lat=("lat", "mean"),
            lng=("lng", "mean"),
            sex=("sex", _first_non_null),
            age=("age", _first_non_null),
            season=("season", _first_non_null),
            n=("lat", "count"),
        )
        .reset_index()
    )
    agg["timestamp"] = agg["day"].astype(str)
    return agg


# =========================
# GeoJSON builders (FAST + UNIQUE COLORS)
# =========================
def _df_points_geojson_fast(df: pd.DataFrame, color_map: dict[str, str]) -> dict:
    if df is None or df.empty:
        return {"type": "FeatureCollection", "features": []}

    d = df.copy()
    d["bear_id"] = d.get("bear_id", "").astype(str)
    d["sex"] = d.get("sex", "").astype(str)
    d["age"] = d.get("age", "").astype(str)
    d["season"] = d.get("season", "").astype(str)

    ts = pd.to_datetime(d.get("timestamp", pd.NaT), errors="coerce")
    d["timestamp_iso"] = ts.dt.strftime("%Y-%m-%d %H:%M:%S").fillna("")

    d["lat"] = pd.to_numeric(d["lat"], errors="coerce")
    d["lng"] = pd.to_numeric(d["lng"], errors="coerce")
    d = d.dropna(subset=["lat", "lng"])

    recs = d[["bear_id", "timestamp_iso", "sex", "age", "season", "lat", "lng"]].to_dict("records")
    feats = []
    for r in recs:
        bid = str(r["bear_id"])
        feats.append(
            {
                "type": "Feature",
                "properties": {
                    "bear_id": bid,
                    "timestamp": r["timestamp_iso"],
                    "sex": r["sex"],
                    "age": r["age"],
                    "season": r["season"],
                    "color": color_map.get(bid, "#ff00ff"),
                },
                "geometry": {"type": "Point", "coordinates": [float(r["lng"]), float(r["lat"])]},
            }
        )

    return {"type": "FeatureCollection", "features": feats}


def _df_paths_geojson_fast(df: pd.DataFrame, color_map: dict[str, str]) -> dict:
    if df is None or df.empty:
        return {"type": "FeatureCollection", "features": []}

    d = df.copy()
    d["bear_id"] = d.get("bear_id", "").astype(str)
    d["timestamp"] = pd.to_datetime(d.get("timestamp", pd.NaT), errors="coerce")

    d["lat"] = pd.to_numeric(d["lat"], errors="coerce")
    d["lng"] = pd.to_numeric(d["lng"], errors="coerce")
    d = d.dropna(subset=["lat", "lng"])

    features = []
    for bear_id, g in d.groupby("bear_id"):
        g = g.sort_values("timestamp")
        coords = g[["lng", "lat"]].astype(float).values.tolist()
        if len(coords) < 2:
            continue
        bid = str(bear_id)
        features.append(
            {
                "type": "Feature",
                "properties": {"bear_id": bid, "color": color_map.get(bid, "#ff00ff")},
                "geometry": {"type": "LineString", "coordinates": coords},
            }
        )

    return {"type": "FeatureCollection", "features": features}


# =========================
# MapLibre HTML
# =========================
def _maplibre_html(
    center_lat: float,
    center_lng: float,
    zoom: float,
    points_geojson: dict,
    paths_geojson: dict,
    mode: str,
    show_points: bool,
    point_size: int,
    line_width: int,
    heat_intensity: int,
    heat_radius: int,
    height: int,
    basemap: str,
    label_lang: str,
) -> str:
    import json as _json

    points_json = _json.dumps(points_geojson)
    paths_json = _json.dumps(paths_geojson)

    mode_paths = "true" if mode == "paths" else "false"
    mode_daily = "true" if mode == "daily" else "false"
    mode_heat = "true" if mode == "heat" else "false"
    show_points_js = "true" if show_points else "false"

    # Build layer toggle HTML depending on active mode
    toggle_html = '<div class="row" style="margin-top:10px;font-weight:600;font-size:12px;">Layer</div>'
    if mode == "paths":
        toggle_html += '<label><input type="checkbox" id="tog-paths" checked/><span class="lsym" style="background:#888;height:3px;border-radius:2px;"></span>Paths</label>'
    if mode in ("paths", "daily") and show_points:
        toggle_html += '<label><input type="checkbox" id="tog-points" checked/><span class="lsym" style="background:#888;border-radius:50%;"></span>Points</label>'
    if mode == "heat":
        toggle_html += '<label><input type="checkbox" id="tog-heat" checked/><span class="lsym" style="background:linear-gradient(#f00,#ff0);border-radius:2px;"></span>Heatmap</label>'

    osm_raster_style = """
{
  "version": 8,
  "sources": {
    "osm": {
      "type": "raster",
      "tiles": ["https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
                "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
                "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png"],
      "tileSize": 256,
      "attribution": "© OpenStreetMap contributors"
    }
  },
  "layers": [
    { "id": "osm", "type": "raster", "source": "osm" }
  ]
}
""".strip()

    carto_light_style = """
{
  "version": 8,
  "sources": {
    "carto": {
      "type": "raster",
      "tiles": ["https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
                "https://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
                "https://c.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
                "https://d.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"],
      "tileSize": 256,
      "attribution": "© OpenStreetMap contributors © CARTO"
    }
  },
  "layers": [
    { "id": "carto", "type": "raster", "source": "carto" }
  ]
}
""".strip()

    carto_dark_style = """
{
  "version": 8,
  "sources": {
    "carto": {
      "type": "raster",
      "tiles": ["https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
                "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
                "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
                "https://d.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"],
      "tileSize": 256,
      "attribution": "© OpenStreetMap contributors © CARTO"
    }
  },
  "layers": [
    { "id": "carto", "type": "raster", "source": "carto" }
  ]
}
""".strip()

    esri_sat_style = """
{
  "version": 8,
  "sources": {
    "esri": {
      "type": "raster",
      "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
      "tileSize": 256,
      "attribution": "Tiles © Esri"
    }
  },
  "layers": [
    { "id": "esri", "type": "raster", "source": "esri" }
  ]
}
""".strip()

    demo_vector_style_url = "https://demotiles.maplibre.org/style.json"

    basemap_js = basemap.strip()
    label_lang_js = label_lang.strip()

    html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="initial-scale=1,maximum-scale=1,user-scalable=no" />
  <link href="https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.css" rel="stylesheet" />
  <script src="https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.js"></script>
  <style>
    html, body {{ margin: 0; padding: 0; height: 100%; }}
    #map {{ width: 100%; height: {height}px; }}
    .panel {{
      position: absolute;
      top: 10px;
      left: 10px;
      z-index: 2;
      background: rgba(255,255,255,0.95);
      border-radius: 10px;
      padding: 10px;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      box-shadow: 0 1px 10px rgba(0,0,0,0.18);
      min-width: 260px;
    }}
    .title {{ font-weight: 700; margin-bottom: 6px; }}
    .muted {{ color: #555; font-size: 12px; }}
    .row {{ margin-top: 6px; font-size: 12px; }}
    .badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 12px;
      background: #f2f2f2;
      margin-left: 6px;
    }}
    .panel label {{
      display: flex; align-items: center; gap: 8px;
      margin: 5px 0; cursor: pointer; font-size: 12px;
    }}
    .lsym {{ width: 12px; height: 12px; flex-shrink: 0; }}
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="panel">
    <div class="title">MapLibre</div>
    <div class="muted">Carpathian Bears Movement</div>
    <div class="row">Mode: <span class="badge">{mode}</span></div>
    <div class="row">Basemap: <span class="badge">{basemap_js}</span></div>
    <div class="row">Labels: <span class="badge">{label_lang_js}</span></div>
    <div class="row muted">Tip: Click a point to see details.</div>
    {toggle_html}
  </div>

  <script>
    const POINTS = {points_json};
    const PATHS  = {paths_json};

    const OSM_RASTER_STYLE = {osm_raster_style};
    const CARTO_LIGHT_STYLE = {carto_light_style};
    const CARTO_DARK_STYLE = {carto_dark_style};
    const ESRI_SAT_STYLE = {esri_sat_style};
    const DEMO_VECTOR_URL = "{demo_vector_style_url}";

    const BASEMAP = "{basemap_js}";
    const LABEL_LANG = "{label_lang_js}";

    function pickStyle() {{
      if (BASEMAP === "OSM Raster") return OSM_RASTER_STYLE;
      if (BASEMAP === "Carto Positron") return CARTO_LIGHT_STYLE;
      if (BASEMAP === "Carto Dark") return CARTO_DARK_STYLE;
      if (BASEMAP === "Esri Satellite") return ESRI_SAT_STYLE;
      return DEMO_VECTOR_URL;
    }}

    const map = new maplibregl.Map({{
      container: 'map',
      style: pickStyle(),
      center: [{center_lng}, {center_lat}],
      zoom: {zoom}
    }});
    map.addControl(new maplibregl.NavigationControl(), 'top-right');

    function applyVectorLabelLanguage(lang) {{
      const style = map.getStyle();
      if (!style || !style.layers) return;
      const tag = (lang && lang !== "local") ? lang : "";
      for (let i = 0; i < style.layers.length; i++) {{
        const layer = style.layers[i];
        if (!layer || layer.type !== "symbol") continue;
        try {{
          if (tag) {{
            map.setLayoutProperty(layer.id, 'text-field', [
              'coalesce',
              ['get', 'name:' + tag],
              ['get', 'name:en'],
              ['get', 'name']
            ]);
          }} else {{
            map.setLayoutProperty(layer.id, 'text-field', [
              'coalesce',
              ['get', 'name'],
              ['get', 'name:en']
            ]);
          }}
        }} catch (e) {{}}
      }}
    }}

    function addDataLayers() {{
      if (!map.getSource('points')) {{
        map.addSource('points', {{ type: 'geojson', data: POINTS }});
      }}
      if (!map.getSource('paths')) {{
        map.addSource('paths', {{ type: 'geojson', data: PATHS }});
      }}

      const MODE_PATHS = {mode_paths};
      const MODE_DAILY = {mode_daily};
      const MODE_HEAT  = {mode_heat};
      const SHOW_POINTS = {show_points_js};

      if (MODE_PATHS && map.getSource('paths') && !map.getLayer('paths-layer')) {{
        map.addLayer({{
          id: 'paths-layer',
          type: 'line',
          source: 'paths',
          paint: {{
            'line-width': {line_width},
            'line-opacity': 0.78,
            'line-color': ['get', 'color']
          }}
        }});
      }}

      if ((MODE_PATHS || MODE_DAILY) && SHOW_POINTS && map.getSource('points') && !map.getLayer('points-layer')) {{
        map.addLayer({{
          id: 'points-layer',
          type: 'circle',
          source: 'points',
          paint: {{
            'circle-radius': {point_size},
            'circle-opacity': 0.9,
            'circle-stroke-width': 1.2,
            'circle-stroke-color': '#ffffff',
            'circle-color': ['get', 'color']
          }}
        }});
      }}

      if (MODE_HEAT && map.getSource('points') && !map.getLayer('heat-layer')) {{
        map.addLayer({{
          id: 'heat-layer',
          type: 'heatmap',
          source: 'points',
          maxzoom: 13,
          paint: {{
            'heatmap-intensity': {max(1, int(heat_intensity))} / 10.0,
            'heatmap-radius': {max(5, int(heat_radius))},
            'heatmap-opacity': 0.85,
            'heatmap-weight': 1.0
          }}
        }});
      }}

      function buildPopupHTML(p) {{
        const bid = (p && p.bear_id) ? p.bear_id : '';
        const t = (p && p.timestamp) ? p.timestamp : '';
        const sx = (p && p.sex) ? p.sex : '';
        const ag = (p && p.age) ? p.age : '';
        const se = (p && p.season) ? p.season : '';

        return '<div style="min-width:240px">' +
          '<h3 style="margin:0 0 8px 0">Bear ' + bid + '</h3>' +
          '<div><b>Time:</b> ' + t + '</div>' +
          '<div><b>Sex:</b> ' + sx + '</div>' +
          '<div><b>Age:</b> ' + ag + '</div>' +
          '<div><b>Season:</b> ' + se + '</div>' +
        '</div>';
      }}

      if (map.getLayer('points-layer')) {{
        map.on('click', 'points-layer', (e) => {{
          const feat = (e.features && e.features[0]) ? e.features[0] : null;
          const props = (feat && feat.properties) ? feat.properties : {{}};
          const html = buildPopupHTML(props);
          new maplibregl.Popup().setLngLat(e.lngLat).setHTML(html).addTo(map);
        }});
        map.on('mouseenter', 'points-layer', () => {{ map.getCanvas().style.cursor = 'pointer'; }});
        map.on('mouseleave', 'points-layer', () => {{ map.getCanvas().style.cursor = ''; }});
      }}

      // Layer Toggles
      const setupToggle = (id, layerIds) => {{
        const el = document.getElementById(id);
        if (!el) return;
        el.addEventListener('change', (ev) => {{
          layerIds.forEach(lyr => {{
            if (map.getLayer(lyr))
              map.setLayoutProperty(lyr, 'visibility', ev.target.checked ? 'visible' : 'none');
          }});
        }});
      }};
      setupToggle('tog-paths',  ['paths-layer']);
      setupToggle('tog-points', ['points-layer']);
      setupToggle('tog-heat',   ['heat-layer']);
    }}

    map.on('load', () => {{
      applyVectorLabelLanguage(LABEL_LANG);
      addDataLayers();
    }});

    map.on('style.load', () => {{
      applyVectorLabelLanguage(LABEL_LANG);
      addDataLayers();
    }});
  </script>
</body>
</html>
"""
    return html


def _render_maplibre(
    tracking_df: pd.DataFrame,
    map_mode: str,
    show_points: bool,
    point_size: int,
    line_width: int,
    heat_intensity: int,
    heat_radius: int,
    basemap: str,
    label_lang: str,
    height: int = 600,
):
    if tracking_df is None or tracking_df.empty:
        st.warning("No data to render on the map.")
        return

    df = tracking_df.copy()
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lng"] = pd.to_numeric(df["lng"], errors="coerce")
    df = df.dropna(subset=["lat", "lng"])
    if df.empty:
        st.warning("No valid lat/lng rows.")
        return

    center_lat = float(df["lat"].mean())
    center_lng = float(df["lng"].mean())

    lat_span = float(df["lat"].max() - df["lat"].min())
    lng_span = float(df["lng"].max() - df["lng"].min())
    span = max(lat_span, lng_span)
    if span < 0.02:
        zoom = 12
    elif span < 0.1:
        zoom = 10
    elif span < 0.5:
        zoom = 8.5
    else:
        zoom = 7.5

    # Build unique color map for currently loaded dataset/view
    bear_ids_in_view = df["bear_id"].astype(str).dropna().unique().tolist()
    color_map = _build_unique_color_map(bear_ids_in_view)

    if map_mode == "daily":
        daily = _df_daily_positions(df)
        points_geojson = _df_points_geojson_fast(daily, color_map=color_map)
        paths_geojson = {"type": "FeatureCollection", "features": []}
    else:
        points_geojson = _df_points_geojson_fast(df, color_map=color_map)
        paths_geojson = _df_paths_geojson_fast(df, color_map=color_map)

    html = _maplibre_html(
        center_lat=center_lat,
        center_lng=center_lng,
        zoom=zoom,
        points_geojson=points_geojson,
        paths_geojson=paths_geojson,
        mode=map_mode,
        show_points=show_points,
        point_size=int(point_size),
        line_width=int(line_width),
        heat_intensity=int(heat_intensity),
        heat_radius=int(heat_radius),
        height=int(height),
        basemap=basemap,
        label_lang=label_lang,
    )
    components.html(html, height=height, scrolling=False)


# =========================
# Build tracking data (cached by inputs)
# =========================
@st.cache_data(show_spinner=False, ttl=60)
def _build_tracking_db(
    bear_ids: tuple[str, ...],
    start_iso: str,
    end_iso: str,
    seasons: tuple[str, ...],
) -> pd.DataFrame:
    start_dt = pd.to_datetime(start_iso)
    end_dt = pd.to_datetime(end_iso)
    season_arg = seasons[0] if len(seasons) == 1 else None

    out = []
    for bid in bear_ids:
        df = _db_get_bear_data_cached(bid, str(start_dt), str(end_dt), season_arg)
        if df is None or df.empty:
            continue
        if len(seasons) > 1 and "season" in df.columns:
            df = df[df["season"].astype(str).isin([str(s) for s in seasons])]
        if "bear_id" not in df.columns:
            df["bear_id"] = bid
        for c in ["sex", "age", "season"]:
            if c not in df.columns:
                df[c] = ""
        df["timestamp"] = pd.to_datetime(df.get("timestamp", pd.NaT), errors="coerce")
        out.append(df)

    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


@st.cache_data(show_spinner=False)
def _build_tracking_csv(
    bear_ids: tuple[str, ...],
    start_iso: str,
    end_iso: str,
    seasons: tuple[str, ...],
) -> pd.DataFrame:
    df_all = _load_carpathian_csv_tracking_cached()
    if df_all is None or df_all.empty:
        return pd.DataFrame()

    start_dt = pd.to_datetime(start_iso)
    end_dt = pd.to_datetime(end_iso)

    out = []
    for bid in bear_ids:
        df = _csv_filter_bear_data(df_all, bid, start_dt, end_dt, seasons=list(seasons) if seasons else None)
        if df is None or df.empty:
            continue
        out.append(df)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


# =========================
# GeoJSON for the shared main map (map.py)
# =========================
@st.cache_data(show_spinner=False)
def get_carpathian_geojson(
    selected_bears,
    start_datetime,
    end_datetime,
    selected_seasons=None,
    map_type="Movement Paths",
    max_points_per_bear=3000,
):
    """
    Return GeoJSON for the Carpathian data as a dict:
        {"points": FeatureCollection, "paths": FeatureCollection}
    Uses the same functions as the Carpathian tab. The database is tried
    first, with an automatic fallback to the CSV files.
    """
    empty = {"type": "FeatureCollection", "features": []}

    if not selected_bears:
        return {"points": empty, "paths": empty}

    # DB-first entscheiden
    bears_df = _db_get_bears_list_cached()
    using_csv = bears_df is None or bears_df.empty

    bear_ids_t = tuple(str(b) for b in selected_bears)
    seasons_t = tuple(selected_seasons) if selected_seasons else tuple()

    if using_csv:
        tracking = _build_tracking_csv(bear_ids_t, str(start_datetime), str(end_datetime), seasons_t)
    else:
        tracking = _build_tracking_db(bear_ids_t, str(start_datetime), str(end_datetime), seasons_t)

    if tracking is None or tracking.empty:
        return {"points": empty, "paths": empty}

    tracking = _downsample_per_bear(tracking, max_points_per_bear=max_points_per_bear)

    bear_ids_in_view = tracking["bear_id"].astype(str).dropna().unique().tolist()
    color_map = _build_unique_color_map(bear_ids_in_view)

    if map_type == "Daily Positions":
        daily = _df_daily_positions(tracking)
        return {
            "points": _df_points_geojson_fast(daily, color_map=color_map),
            "paths": empty,
        }

    return {
        "points": _df_points_geojson_fast(tracking, color_map=color_map),
        "paths": _df_paths_geojson_fast(tracking, color_map=color_map),
    }


def get_carpathian_options():
    """
    Return (bears_list, seasons, min_date, max_date) for the sidebar
    filters. Database first, CSV fallback.
    """
    default_seasons = ["Winter sleep", "Den exit and reproduction", "Forest fruits", "Hyperphagia"]
    bears_df = _db_get_bears_list_cached()
    using_csv = bears_df is None or bears_df.empty

    if using_csv:
        csv_track = _load_carpathian_csv_tracking_cached()
        bears_df = _csv_get_bears_list(csv_track)
        seasons = _csv_get_distinct_seasons(csv_track) or default_seasons
        min_date, max_date = _csv_get_date_range(csv_track)
    else:
        if "bear_id" not in bears_df.columns and "id" in bears_df.columns:
            bears_df = bears_df.rename(columns={"id": "bear_id"})
        seasons = _db_get_seasons_cached() or default_seasons
        min_date, max_date = _db_get_date_range_cached()

    if bears_df is None or bears_df.empty:
        bears = []
    else:
        bears = sorted(bears_df["bear_id"].astype(str).unique().tolist())

    return bears, seasons, min_date, max_date


# =========================
# Main UI
# =========================
def display_carpathian_bears_section():
    st.title("Carpathian Bears Movement Analysis")

    # DB-first
    bears_df = _db_get_bears_list_cached()
    using_csv = False

    if bears_df is None or bears_df.empty:
        using_csv = True
        st.info(
            "Local mode: no database records found, or no connection. "
            "Carpathian data is loaded automatically from the CSV files in "
            "the project."
        )
        tracking_csv_cache = _load_carpathian_csv_tracking_cached()
        bears_df = _csv_get_bears_list(tracking_csv_cache)

        seasons = _csv_get_distinct_seasons(tracking_csv_cache)
        if not seasons:
            seasons = ["Winter sleep", "Den exit and reproduction", "Forest fruits", "Hyperphagia"]

        min_date, max_date = _csv_get_date_range(tracking_csv_cache)
    else:
        if "bear_id" not in bears_df.columns and "id" in bears_df.columns:
            bears_df = bears_df.rename(columns={"id": "bear_id"})
        for col in ["bear_id", "sex", "age"]:
            if col not in bears_df.columns:
                bears_df[col] = ""
        seasons = _db_get_seasons_cached()
        if not seasons:
            seasons = ["Winter sleep", "Den exit and reproduction", "Forest fruits", "Hyperphagia"]
        min_date, max_date = _db_get_date_range_cached()

    if bears_df is None or bears_df.empty:
        st.error("No bear data found (DB + CSV fallback both empty).")
        return

    tabs = st.tabs(
        [
            "Movement Map (MapLibre)",
            "Home Range Analysis",
            "Seasonal Patterns",
            "Data Explorer",
            "About",
        ]
    )

    # =========================
    # Sidebar filters (FORM)
    # =========================
    with st.sidebar:
        st.header("Filters")

        with st.form("carpathian_filters_form"):
            all_bears = sorted(bears_df["bear_id"].astype(str).unique().tolist())

            select_all_bears = st.checkbox("Select All Bears", value=False)
            if select_all_bears:
                selected_bears = all_bears
            else:
                default_sel = all_bears[: min(2, len(all_bears))]
                selected_bears = st.multiselect("Select Bears", options=all_bears, default=default_sel)

            all_sexes = sorted([s for s in bears_df["sex"].dropna().unique().tolist() if str(s).strip() != ""])
            select_all_sexes = st.checkbox("Select All Sexes", value=True)
            selected_sexes = all_sexes if select_all_sexes else st.multiselect("Filter by Sex", options=all_sexes, default=all_sexes)

            all_ages = sorted([a for a in bears_df["age"].dropna().unique().tolist() if str(a).strip() != ""])
            select_all_ages = st.checkbox("Select All Age Classes", value=True)
            selected_ages = all_ages if select_all_ages else st.multiselect("Filter by Age Class", options=all_ages, default=all_ages)

            select_all_seasons = st.checkbox("Select All Seasons", value=True, help=SEASON_HELP)
            selected_seasons = seasons if select_all_seasons else st.multiselect(
                "Filter by Season", options=seasons, default=seasons, help=SEASON_HELP)

            st.subheader("Date Range")
            date_range = st.date_input(
                "Select Date Range",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
            )
            if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
                start_date, end_date = date_range
            else:
                start_date, end_date = min_date, max_date

            st.subheader("Map Settings")

            basemap = st.selectbox(
                "Basemap",
                options=[
                    "OSM Raster",
                    "Carto Positron",
                    "Carto Dark",
                    "Esri Satellite",
                    "MapLibre Demo Vector",
                ],
                index=0,
            )

            label_lang = st.selectbox(
                "Label language (Vector only)",
                options=[
                    ("local", "Local"),
                    ("en", "English"),
                    ("de", "German"),
                    ("fr", "French"),
                    ("es", "Spanish"),
                    ("it", "Italian"),
                    ("ja", "Japanese"),
                ],
                index=1,
                format_func=lambda x: x[1],
            )[0]

            map_type = st.selectbox(
                "Map Type",
                options=["Movement Paths", "Heatmap", "Daily Positions"],
                index=0,
            )

            st.subheader("Performance")
            max_points_per_bear = st.slider(
                "Max points per bear (downsampling)",
                min_value=300,
                max_value=20000,
                value=3000,
                step=100,
                help="Lower = faster. 3000 is a good default.",
            )

            line_width = 3
            point_size = 5
            show_points = True
            heat_intensity = 10
            heat_radius = 15

            if map_type == "Movement Paths":
                line_width = st.slider("Path Width", 1, 10, 3)
                show_points = st.checkbox("Show Points", value=False)
                if show_points:
                    point_size = st.slider("Point Size", 1, 20, 5)
            elif map_type == "Heatmap":
                heat_intensity = st.slider("Heatmap Intensity", 1, 50, 10)
                heat_radius = st.slider("Heatmap Radius", 5, 50, 15)
                show_points = False
            else:
                point_size = st.slider("Point Size", 1, 20, 8)
                show_points = True

            apply = st.form_submit_button("Apply", type="primary")

        if "carpathian_initialized" not in st.session_state:
            st.session_state.carpathian_initialized = True
            apply = True # Trigger initial load

    # =========================
    # Filter bears by sex/age
    # =========================
    filtered_bears = []
    for bear in selected_bears:
        b = bears_df[bears_df["bear_id"].astype(str) == str(bear)]
        if b.empty:
            continue
        bear_sex = b["sex"].iloc[0] if "sex" in b.columns else None
        bear_age = b["age"].iloc[0] if "age" in b.columns else None

        if selected_sexes and bear_sex is not None and str(bear_sex).strip() != "" and bear_sex not in selected_sexes:
            continue
        if selected_ages and bear_age is not None and str(bear_age).strip() != "" and bear_age not in selected_ages:
            continue

        filtered_bears.append(str(bear))

    start_datetime = datetime.combine(start_date, datetime.min.time())
    end_datetime = datetime.combine(end_date, datetime.max.time())

    # =========================
    # Tab 0: Movement Map
    # =========================
    with tabs[0]:
        st.header("Bear Movement Map (MapLibre)")

        if not filtered_bears:
            st.warning("Please select at least one bear to display data.")
        else:
            with st.spinner("Loading & preparing data..."):
                bear_ids_t = tuple(filtered_bears)
                seasons_t = tuple(selected_seasons) if selected_seasons else tuple()

                if using_csv:
                    tracking_data = _build_tracking_csv(bear_ids_t, str(start_datetime), str(end_datetime), seasons_t)
                else:
                    tracking_data = _build_tracking_db(bear_ids_t, str(start_datetime), str(end_datetime), seasons_t)

                if tracking_data is None or tracking_data.empty:
                    st.warning("No data available for the selected filters.")
                else:
                    tracking_data = _downsample_per_bear(tracking_data, max_points_per_bear=max_points_per_bear)

                    if map_type == "Daily Positions":
                        tracking_data = _df_daily_positions(tracking_data)

                    mode = "paths"
                    if map_type == "Heatmap":
                        mode = "heat"
                    elif map_type == "Daily Positions":
                        mode = "daily"

                    _render_maplibre(
                        tracking_df=tracking_data,
                        map_mode=mode,
                        show_points=show_points if mode != "heat" else False,
                        point_size=int(point_size),
                        line_width=int(line_width),
                        heat_intensity=int(heat_intensity),
                        heat_radius=int(heat_radius),
                        basemap=basemap,
                        label_lang=label_lang,
                        height=600,
                    )

                    with st.expander("Show loaded records (preview)", expanded=False):
                        show_cols = [c for c in ["bear_id", "timestamp", "sex", "age", "season", "lat", "lng"] if c in tracking_data.columns]
                        st.dataframe(tracking_data[show_cols].head(300))

        st.caption(
            "Note: label language only applies to vector styles, for example "
            "MapLibre Demo Vector. Raster maps (OSM, Carto, Esri) carry labels "
            "baked into the tiles."
        )

    # =========================
    # Other tabs (unchanged)
    # =========================
    with tabs[1]:
        st.header("Home Range Analysis")
        if using_csv:
            st.info("Home range analysis requires database tables (MCP/KDE). This tab is disabled in CSV mode.")
        else:
            st.info("Database available: existing home range analyses can be plugged in here.")

    with tabs[2]:
        st.header("Seasonal Movement Patterns")
        if using_csv:
            st.info("Seasonal patterns require database tables. This tab is disabled in CSV mode.")
        else:
            st.info("Database available: existing seasonal analyses can be plugged in here.")

    with tabs[3]:
        st.header("Data Explorer")
        if using_csv:
            st.info("CSV-Modus: Zeige CSV-Trackingdaten (Preview).")
            df_all = _load_carpathian_csv_tracking_cached()
            if df_all is not None and not df_all.empty:
                st.dataframe(df_all.head(1000))
            else:
                st.warning("CSV cache ist leer.")
        else:
            st.info("Database mode: database explorer queries can be shown here.")

    with tabs[4]:
        st.header("About")
        st.markdown(
            """
**Unique colour per bear**
- Every bear_id receives **one unique colour** in the current view, with no duplicates.
- A bear newly appearing in the database is automatically assigned a free colour.

**Performance**
- The Apply button (inside a form) prevents excessive reruns.
- Caching and downsampling substantially reduce load time.
"""
        )


if __name__ == "__main__":
    display_carpathian_bears_section()