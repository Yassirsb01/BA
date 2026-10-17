"""
maplibre_component.py
=====================
Shared MapLibre main map for all three subsystems.

Two implementation details worth noting:
  - setStyle() combined with map.once('style.load') and diff:false gives
    reliable layer restoration after a base map change.
  - addLayer with beforeId (before the first symbol layer) keeps city and
    country labels visible above the data layers.
"""

import json
import streamlit.components.v1 as components


# The order here is the order in the selection box. Satellite comes first
# because it is the default: judging bear movement depends on the terrain
# (forest, clearings, valleys), which a vector map does not show. All
# other styles remain selectable.
DEFAULT_BASEMAP = "Esri Satellite"

BASEMAP_NAMES = ["Esri Satellite", "Esri Satellite + labels",
                 "Liberty", "Bright", "Positron", "Dark", "OSM Raster"]

# Free elevation data without an API key (the source used by the official
# MapLibre 3D terrain example), identical to animation_component.py and
# japan_map_component.py so that all three maps behave the same.
TERRAIN_TILEJSON = "https://tiles.mapterhorn.com/tilejson.json"


def _build_styles():
    """All styles as a dict {name: URL string or style object}."""
    vector = {
        "Liberty":  "https://tiles.openfreemap.org/styles/liberty",
        "Bright":   "https://tiles.openfreemap.org/styles/bright",
        "Positron": "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        "Dark":     "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
    }
    # Important for raster sources: maxzoom MUST be set, otherwise
    # MapLibre requests tiles that do not exist when zooming in. Esri does
    # not answer with an error but with a valid tile reading "Map data not
    # yet available", which makes the map look empty or broken. With
    # maxzoom, MapLibre upscales the last available tile instead:
    # slightly blurry, but always an image.
    raster = {
        "OSM Raster": {
            "version": 8,
            "sources": {"osm": {
                "type": "raster",
                "tiles": ["https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
                          "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
                          "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png"],
                "tileSize": 256, "maxzoom": 19,
                "attribution": "(c) OpenStreetMap contributors"}},
            "layers": [{"id": "osm", "type": "raster", "source": "osm"}],
        },
        "Esri Satellite": {
            "version": 8,
            "sources": {"esri": {
                "type": "raster",
                "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
                "tileSize": 256, "maxzoom": 17,
                "attribution": "Satellite imagery (c) Esri, Maxar, Earthstar Geographics"}},
            "layers": [{"id": "esri", "type": "raster", "source": "esri"}],
        },
        "Esri Satellite + labels": {
            "version": 8,
            "sources": {
                "esri": {
                    "type": "raster",
                    "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
                    "tileSize": 256, "maxzoom": 17,
                    "attribution": "Satellite imagery (c) Esri, Maxar, Earthstar Geographics"},
                "esri-ref": {
                    "type": "raster",
                    "tiles": ["https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"],
                    "tileSize": 256, "maxzoom": 17},
            },
            "layers": [
                {"id": "esri", "type": "raster", "source": "esri"},
                {"id": "esri-ref", "type": "raster", "source": "esri-ref"},
            ],
        },
    }
    return {**vector, **raster}


def _empty_fc():
    return {"type": "FeatureCollection", "features": []}


def render_maplibre(
    japan=None,
    carpathian=None,
    simulation=None,
    wolf_lynx=None,
    gbif_bears=None,
    basemap: str = DEFAULT_BASEMAP,
    terrain3d: bool = False,
    center=None,
    zoom: float = None,
    initial_visible: set = None,
    refit_on_load: set = None,
    height: int = 650,
):
    japan = japan or {}
    carpathian = carpathian or {}
    simulation = simulation or {}
    wolf_lynx = wolf_lynx or {}
    gbif_bears = gbif_bears or {}

    jp_deterrents = japan.get("deterrents", _empty_fc())
    jp_markers    = japan.get("markers", _empty_fc())
    jp_polygons   = japan.get("polygons", _empty_fc())
    cp_points     = carpathian.get("points", _empty_fc())
    cp_paths      = carpathian.get("paths", _empty_fc())
    sim_points    = simulation.get("points", _empty_fc())
    sim_paths     = simulation.get("paths", _empty_fc())
    # wolf_lynx and gbif_bears already arrive as a finished
    # FeatureCollection rather than a dict of sub-categories, so they are
    # taken over directly.
    wolf_lynx_fc  = wolf_lynx if wolf_lynx.get("type") == "FeatureCollection" else _empty_fc()
    gbif_bears_fc = gbif_bears if gbif_bears.get("type") == "FeatureCollection" else _empty_fc()

    has_japan = bool(japan)
    has_carpathian = bool(carpathian)
    has_simulation = bool(simulation)
    has_wolf_lynx = bool(wolf_lynx_fc.get("features"))
    has_gbif_bears = bool(gbif_bears_fc.get("features"))

    if center is None:
        center = (45.0, 80.0)
    center_lat, center_lng = center
    if zoom is None:
        zoom = 2
    if basemap not in BASEMAP_NAMES:
        basemap = DEFAULT_BASEMAP

    t3d_checked = " checked" if terrain3d else ""
    t3d_js = "true" if terrain3d else "false"

    styles_js = json.dumps(_build_styles())
    refit_json = json.dumps(sorted(refit_on_load)) if refit_on_load else "[]"

    data = {
        "jp_deterrents": json.dumps(jp_deterrents),
        "jp_markers":    json.dumps(jp_markers),
        "jp_polygons":   json.dumps(jp_polygons),
        "cp_points":     json.dumps(cp_points),
        "cp_paths":      json.dumps(cp_paths),
        "sim_points":    json.dumps(sim_points),
        "sim_paths":     json.dumps(sim_paths),
        "wolf_lynx":     json.dumps(wolf_lynx_fc),
        "gbif_bears":    json.dumps(gbif_bears_fc),
    }

    # Which layers should already be ticked when rendering?
    # - initial_visible comes from the URL query parameters, the last
    #   known client state, and is restored exactly.
    # - On a first start (no URL parameters yet, initial_visible is None)
    #   the previous default applies: simulation preselected, rest off.
    if initial_visible is None:
        default_checked = {"simulation"} if has_simulation else set()
    else:
        default_checked = set(initial_visible)

    checkbox_rows = ""
    if has_japan:
        n = len(jp_deterrents.get("features", [])) + len(jp_markers.get("features", []))
        chk = " checked" if "japan" in default_checked else ""
        checkbox_rows += (f'<label><input type="checkbox" id="tg-japan"{chk} /> '
                          f'Japan Deterrents <span class="cnt">{n}</span>'
                          f'<span class="dot" style="background:#d33"></span></label>')
    if has_carpathian:
        n = len(cp_points.get("features", []))
        chk = " checked" if "carpathian" in default_checked else ""
        checkbox_rows += (f'<label><input type="checkbox" id="tg-carpathian"{chk} /> '
                          f'Carpathian GPS <span class="cnt">{n}</span>'
                          f'<span class="dot" style="background:#1d6fb8"></span></label>')
    if has_simulation:
        n = len(sim_points.get("features", []))
        chk = " checked" if "simulation" in default_checked else ""
        checkbox_rows += (f'<label><input type="checkbox" id="tg-simulation"{chk} /> '
                          f'Simulation <span class="cnt">{n}</span>'
                          f'<span class="dot" style="background:#e8830c"></span></label>')
    if has_wolf_lynx:
        n = len(wolf_lynx_fc.get("features", []))
        chk = " checked" if "wolf_lynx" in default_checked else ""
        checkbox_rows += (f'<label><input type="checkbox" id="tg-wolf-lynx"{chk} /> '
                          f'Wolf/Lynx (BfN) <span class="cnt">{n}</span>'
                          f'<span class="dot" style="background:#5b3a29"></span></label>')
    if has_gbif_bears:
        n = len(gbif_bears_fc.get("features", []))
        chk = " checked" if "gbif_bears" in default_checked else ""
        checkbox_rows += (f'<label><input type="checkbox" id="tg-gbif-bears"{chk} /> '
                          f'Bear sightings (GBIF) <span class="cnt">{n}</span>'
                          f'<span class="dot" style="background:#c77b2e"></span></label>')
    if not checkbox_rows:
        checkbox_rows = '<div class="muted">No data loaded.</div>'

    bm_options = "".join(
        f'<option value="{name}"{" selected" if name == basemap else ""}>{name}</option>'
        for name in BASEMAP_NAMES
    )

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
      position: absolute; top: 10px; left: 10px; z-index: 2;
      background: rgba(255,255,255,0.96); border-radius: 10px;
      padding: 10px 12px; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      box-shadow: 0 1px 10px rgba(0,0,0,0.18); min-width: 230px;
    }}
    .panel .title {{ font-weight: 700; margin-bottom: 8px; font-size: 14px; }}
    .panel label {{ display: flex; align-items: center; gap: 8px; margin: 6px 0;
                    cursor: pointer; font-size: 13px; }}
    .cnt {{ color:#888; font-size:11px; margin-left:auto; }}
    .dot {{ display:inline-block; width:11px; height:11px; border-radius:50%; margin-left:8px; }}
    .muted {{ color:#666; font-size:12px; }}
    .sep {{ border-top:1px solid #e6e6e6; margin:9px 0 7px; }}
    .bm-label {{ font-size:12px; color:#555; display:block; margin-bottom:4px; }}
    #basemap-select {{ width:100%; padding:5px 6px; border-radius:6px;
                       border:1px solid #ccc; font-size:13px; background:#fff; cursor:pointer; }}
    .terrain-note {{ font-size:11px; color:#b4553c; line-height:1.4; display:none; }}

    .draw-panel {{ top:10px; right:10px; left:auto; min-width:220px; }}
    .draw-mode-row {{ display:flex; gap:6px; margin-bottom:8px; }}
    .draw-mode-btn {{ flex:1; padding:6px 4px; border-radius:6px; border:1px solid #ccc;
                       background:#f7f7f7; cursor:pointer; font-size:12px; }}
    .draw-mode-btn.active {{ background:#2a6fdb; color:#fff; border-color:#2a6fdb; }}
    .draw-hint {{ font-size:11.5px; color:#666; margin-bottom:8px; line-height:1.4; min-height:32px; }}
    #draw-name-input {{ width:100%; padding:5px 6px; border-radius:6px; border:1px solid #ccc;
                         font-size:12px; margin-bottom:8px; box-sizing:border-box; display:none; }}
    .draw-actions {{ display:flex; gap:6px; }}
    .draw-actions button {{ flex:1; padding:6px 4px; border-radius:6px; border:1px solid #ccc;
                             font-size:12px; cursor:pointer; }}
    #draw-save-btn {{ background:#2a8f2a; color:#fff; border-color:#2a8f2a; }}
    #draw-save-btn:disabled {{ background:#a8d5a8; border-color:#a8d5a8; cursor:not-allowed; }}
    #draw-undo-btn, #draw-cancel-btn {{ background:#f7f7f7; }}
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="panel">
    <div class="title">Show layers</div>
    {checkbox_rows}
    <div class="sep"></div>
    <label class="bm-label">Base map</label>
    <select id="basemap-select">{bm_options}</select>
    <label><input type="checkbox" id="toggle-3d"{t3d_checked} /> 3D terrain</label>
    <div class="terrain-note" id="terrain-note">Elevation data unavailable; the map stays in 2D.</div>
  </div>

  <div class="panel draw-panel">
    <div class="title">New entry (Japan)</div>
    <div class="draw-mode-row">
      <button class="draw-mode-btn" id="mode-marker" title="Place a single point">Marker</button>
      <button class="draw-mode-btn" id="mode-polygon" title="Outline an area">Area</button>
    </div>
    <div class="draw-hint" id="draw-hint">Choose a mode, then click on the map.</div>
    <input type="text" id="draw-name-input" placeholder="Name of the area" />
    <div class="draw-actions">
      <button id="draw-undo-btn" style="display:none">Undo last point</button>
      <button id="draw-cancel-btn" style="display:none">Cancel</button>
      <button id="draw-save-btn" disabled>Save</button>
    </div>
  </div>

  <script>
    const STYLES = {styles_js};
    // Layers whose data changed since the last render, for example a
    // different bear or period. On load the map navigates to them
    // automatically, even if the layer was already visible.
    const REFIT_ON_LOAD = {refit_json};
    const DATA = {{
      jp_deterrents: {data["jp_deterrents"]},
      jp_markers:    {data["jp_markers"]},
      jp_polygons:   {data["jp_polygons"]},
      cp_points:     {data["cp_points"]},
      cp_paths:      {data["cp_paths"]},
      sim_points:    {data["sim_points"]},
      sim_paths:     {data["sim_paths"]},
      wolf_lynx:     {data["wolf_lynx"]},
      gbif_bears:    {data["gbif_bears"]}
    }};

    const GROUPS = {{
      japan:      {{ id:'tg-japan',      layers:['jp-deterrents','jp-markers','jp-polygons-fill','jp-polygons-line'],
                     fcs:[DATA.jp_deterrents, DATA.jp_markers, DATA.jp_polygons] }},
      carpathian: {{ id:'tg-carpathian', layers:['cp-points','cp-paths'],
                     fcs:[DATA.cp_points, DATA.cp_paths] }},
      simulation: {{ id:'tg-simulation', layers:['sim-points','sim-paths'],
                     fcs:[DATA.sim_points, DATA.sim_paths] }},
      wolf_lynx:  {{ id:'tg-wolf-lynx',  layers:['wolf-lynx-fill','wolf-lynx-line'],
                     fcs:[DATA.wolf_lynx] }},
      gbif_bears: {{ id:'tg-gbif-bears', layers:['gbif-bears-points'],
                     fcs:[DATA.gbif_bears] }}
    }};

    const TERRAIN_TILEJSON = "{TERRAIN_TILEJSON}";

    const map = new maplibregl.Map({{
      container: 'map',
      style: STYLES["{basemap}"],
      center: [{center_lng}, {center_lat}],
      zoom: {zoom},
      maxPitch: 85   // without this the camera cannot be pitched into the 3D view
    }});
    // visualizePitch shows the pitch in the compass; otherwise it is hard
    // to tell which inclination the view is currently at.
    map.addControl(new maplibregl.NavigationControl({{ visualizePitch:true }}), 'top-right');

    // -------------------------------------------------------
    // Write the state (centre, zoom, base map, visible layers) into the
    // URL of the surrounding Streamlit window. On the next rerun, for
    // example after applying a filter, Python can read it through
    // st.query_params and resume exactly there instead of resetting the
    // map to the default view. This is not a true return channel, which
    // would require declare_component(), but it is sufficient to carry
    // the camera and layer state across reruns.
    // -------------------------------------------------------
    let currentStyleName = "{basemap}";

    function debounce(fn, wait) {{
      let t;
      return (...args) => {{ clearTimeout(t); t = setTimeout(() => fn(...args), wait); }};
    }}

    function saveStateToUrl() {{
      try {{
        const parentWin = window.parent;
        if (!parentWin || parentWin === window) return;

        const params = new URLSearchParams(parentWin.location.search);
        const c = map.getCenter();
        params.set('m_lat', c.lat.toFixed(5));
        params.set('m_lng', c.lng.toFixed(5));
        params.set('m_zoom', map.getZoom().toFixed(2));
        params.set('m_style', currentStyleName);
        params.set('m_3d', terrain3d ? '1' : '0');

        const visible = Object.keys(GROUPS).filter(k => {{
          const cb = document.getElementById(GROUPS[k].id);
          return cb && cb.checked;
        }});
        params.set('m_layers', visible.join(','));

        const newUrl = parentWin.location.pathname + '?' + params.toString() + parentWin.location.hash;
        parentWin.history.replaceState(null, '', newUrl);
      }} catch (e) {{
        // For example a cross-origin restriction: ignored silently, the
        // map stays fully usable, only without state persistence.
      }}
    }}

    const saveStateDebounced = debounce(saveStateToUrl, 400);

    // -------------------------------------------------------
    // Find the id of the first symbol layer.
    // Own layers are inserted BEFORE it, so that vector labels (cities,
    // countries) are still rendered ABOVE the data.
    // Raster styles have no symbol layers, so beforeId stays undefined and the layer is appended.
    // -------------------------------------------------------
    function firstSymbolLayerId() {{
      const layers = (map.getStyle() || {{}}).layers || [];
      for (const l of layers) {{
        if (l.type === 'symbol') return l.id;
      }}
      return undefined;
    }}

    function addLayerSafe(spec) {{
      if (map.getLayer(spec.id)) return;
      map.addLayer(spec, firstSymbolLayerId());  // always BEFORE labels
    }}

    // -------------------------------------------------------
    // 3D terrain, taken from animation_component.py with the same
    // controls and the same failure behaviour: if the elevation data
    // cannot be reached the map stays fully usable in 2D, the toggle
    // resets itself and a note is shown instead of an error.
    // -------------------------------------------------------
    let terrain3d = {t3d_js};

    function applyTerrain(on) {{
      try {{
        if (map.getLayer('hillshade')) {{
          map.setLayoutProperty('hillshade','visibility', on ? 'visible' : 'none');
        }}
        if (on) {{
          if (map.getSource('terrain-dem')) map.setTerrain({{ source:'terrain-dem', exaggeration:1.4 }});
          map.easeTo({{ pitch:62, duration:700 }});
        }} else {{
          map.setTerrain(null);
          map.easeTo({{ pitch:0, duration:500 }});
        }}
      }} catch (e) {{
        console.warn('Terrain could not be applied:', e);
        showTerrainNote();
      }}
    }}

    function showTerrainNote() {{
      const n = document.getElementById('terrain-note');
      if (n) n.style.display = 'block';
      const cb = document.getElementById('toggle-3d');
      if (cb) cb.checked = false;
      terrain3d = false;
    }}

    // Report missing elevation tiles without blocking the map
    map.on('error', (e) => {{
      const msg = (e && e.error && e.error.message) || '';
      if (terrain3d && /terrain|dem|mapterhorn/i.test(msg)) showTerrainNote();
    }});

    function setVis(ids, vis) {{
      ids.forEach(id => {{
        if (map.getLayer(id))
          map.setLayoutProperty(id, 'visibility', vis ? 'visible' : 'none');
      }});
    }}

    // -------------------------------------------------------
    // Add sources and layers (idempotent)
    // -------------------------------------------------------
    function addSourcesAndLayers() {{
      const addSrc = (id, d) => {{ if (!map.getSource(id)) map.addSource(id, {{ type:'geojson', data:d }}); }};

      // Elevation model and hillshading make slope direction and
      // landform visible, which is often hard to read on imagery alone.
      // Hillshading is toggled together with 3D and inserted at the
      // bottom so that all data layers above it stay readable.
      if (!map.getSource('terrain-dem')) {{
        try {{ map.addSource('terrain-dem', {{ type:'raster-dem', url:TERRAIN_TILEJSON }}); }}
        catch (e) {{ console.warn('Terrain source unavailable:', e); }}
      }}
      // addLayerSafe inserts before the first symbol layer. Because
      // hillshading is created BEFORE all data layers and those are then
      // inserted at the same position, they automatically end up above
      // it. Raster styles such as satellite have no symbol layers, so
      // hillshading is simply placed on top of the imagery.
      if (map.getSource('terrain-dem')) {{
        addLayerSafe({{ id:'hillshade', type:'hillshade', source:'terrain-dem',
          layout:{{ visibility:'none' }},
          paint:{{ 'hillshade-exaggeration':0.45, 'hillshade-shadow-color':'#3b3226' }} }});
      }}

      addSrc('jp_deterrents', DATA.jp_deterrents);
      addSrc('jp_markers',    DATA.jp_markers);
      addSrc('jp_polygons',   DATA.jp_polygons);
      addSrc('cp_points',     DATA.cp_points);
      addSrc('cp_paths',      DATA.cp_paths);
      addSrc('sim_points',    DATA.sim_points);
      addSrc('sim_paths',     DATA.sim_paths);
      addSrc('wolf_lynx',     DATA.wolf_lynx);
      addSrc('gbif_bears',    DATA.gbif_bears);

      // JAPAN
      addLayerSafe({{ id:'jp-polygons-fill', type:'fill', source:'jp_polygons',
        paint:{{ 'fill-color':'#2a8f2a','fill-opacity':0.20 }} }});
      addLayerSafe({{ id:'jp-polygons-line', type:'line', source:'jp_polygons',
        paint:{{ 'line-color':'#2a8f2a','line-width':2 }} }});
      addLayerSafe({{ id:'jp-deterrents', type:'circle', source:'jp_deterrents',
        paint:{{ 'circle-radius':7,'circle-color':'#d33','circle-stroke-width':2,'circle-stroke-color':'#fff' }} }});
      addLayerSafe({{ id:'jp-markers', type:'circle', source:'jp_markers',
        paint:{{ 'circle-radius':7,'circle-color':'#3186cc','circle-stroke-width':2,'circle-stroke-color':'#fff' }} }});

      // Temporary preview while drawing, before anything is saved. It
      // uses a clearly distinct colour and shape so it cannot be confused
      // with already stored entries.
      addSrc('draw_marker_preview', {{ type:'FeatureCollection', features:[] }});
      addSrc('draw_polygon_preview', {{ type:'FeatureCollection', features:[] }});
      addSrc('draw_polygon_points', {{ type:'FeatureCollection', features:[] }});
      addLayerSafe({{ id:'draw-marker-preview', type:'circle', source:'draw_marker_preview',
        paint:{{ 'circle-radius':9,'circle-color':'#ff9800','circle-stroke-width':2,'circle-stroke-color':'#fff' }} }});
      addLayerSafe({{ id:'draw-polygon-fill', type:'fill', source:'draw_polygon_preview',
        paint:{{ 'fill-color':'#ff9800','fill-opacity':0.25 }} }});
      addLayerSafe({{ id:'draw-polygon-line', type:'line', source:'draw_polygon_preview',
        paint:{{ 'line-color':'#ff9800','line-width':2,'line-dasharray':[2,1.5] }} }});
      addLayerSafe({{ id:'draw-polygon-points', type:'circle', source:'draw_polygon_points',
        paint:{{ 'circle-radius':5,'circle-color':'#ff9800','circle-stroke-width':1.5,'circle-stroke-color':'#fff' }} }});

      // CARPATHIAN
      addLayerSafe({{ id:'cp-paths', type:'line', source:'cp_paths',
        paint:{{ 'line-width':3,'line-opacity':0.85,'line-color':['coalesce',['get','color'],'#1d6fb8'] }} }});
      addLayerSafe({{ id:'cp-points', type:'circle', source:'cp_points',
        paint:{{ 'circle-radius':4,'circle-opacity':0.9,'circle-stroke-width':1,'circle-stroke-color':'#fff',
                 'circle-color':['coalesce',['get','color'],'#1d6fb8'] }} }});

      // SIMULATION
      // Line: the real GPS path (blue, dashed)
      addLayerSafe({{ id:'sim-paths', type:'line', source:'sim_paths',
        paint:{{ 'line-width':3,
                 'line-color':['coalesce',['get','color'],'#1565c0'],
                 'line-dasharray':[2,2],
                 'line-opacity':0.9 }} }});
      // Points: real steps (blue, larger) and alternatives (orange,
      // smaller). Colour and radius are driven by feature properties.
      addLayerSafe({{ id:'sim-points', type:'circle', source:'sim_points',
        paint:{{
          'circle-color': ['coalesce',['get','color'],'#ff9800'],
          'circle-radius': ['case',['==',['get','type'],'real'],7,5],
          'circle-opacity': ['case',['==',['get','type'],'real'],0.95,0.70],
          'circle-stroke-width': ['case',['==',['get','type'],'real'],2,1],
          'circle-stroke-color': '#fff'
        }} }});

      // WOLF/LYNX (BfN, occupied 10x10 km grid cells as polygons).
      // Deliberately only a thin outline instead of a solid fill: a cell
      // means "at least one C1/C2 record somewhere in here", not a precise
      // position. A solid fill would suggest an accuracy the data does not
      // support, and several adjacent cells would read as one continuous
      // area.
      addLayerSafe({{ id:'wolf-lynx-fill', type:'fill', source:'wolf_lynx',
        paint:{{ 'fill-color':['coalesce',['get','color'],'#5b3a29'],'fill-opacity':0.08 }} }});
      addLayerSafe({{ id:'wolf-lynx-line', type:'line', source:'wolf_lynx',
        paint:{{ 'line-color':['coalesce',['get','color'],'#5b3a29'],'line-width':1.2,'line-opacity':0.8 }} }});

      // BEAR SIGHTINGS (GBIF, points for DE and RO)
      addLayerSafe({{ id:'gbif-bears-points', type:'circle', source:'gbif_bears',
        paint:{{ 'circle-radius':5,'circle-opacity':0.85,'circle-stroke-width':1,'circle-stroke-color':'#fff',
                 'circle-color':['coalesce',['get','color'],'#5b3a29'] }} }});
    }}

    // Restore visibility from the checkboxes; the DOM is preserved
    function applyVisibilityFromCheckboxes() {{
      Object.values(GROUPS).forEach(g => {{
        const cb = document.getElementById(g.id);
        setVis(g.layers, cb ? cb.checked : false);
      }});
    }}

    // -------------------------------------------------------
    // Popups, registered only once
    // -------------------------------------------------------
    function wirePopups() {{
      const pop = (e, html) => new maplibregl.Popup().setLngLat(e.lngLat).setHTML(html).addTo(map);

      map.on('click','jp-deterrents',(e)=>{{ const p=e.features[0].properties||{{}};
        pop(e,'<h3>Deterrent</h3><b>ID:</b> '+(p.directory_name||p.id||'N/A')+
              '<br><b>Device Images:</b> '+(p.device_count||0)+
              '<br><b>Trail Images:</b> '+(p.trail_count||0)); }});
      map.on('mouseenter','jp-deterrents',()=>map.getCanvas().style.cursor='pointer');
      map.on('mouseleave','jp-deterrents',()=>map.getCanvas().style.cursor='');

      map.on('click','jp-markers',(e)=>{{ const p=e.features[0].properties||{{}};
        pop(e,'<h3>Custom Marker</h3><b>ID:</b> '+(p.id||'N/A')+
              '<br><b>Time:</b> '+(p.timestamp||'')); }});

      map.on('click','cp-points',(e)=>{{ const p=e.features[0].properties||{{}};
        const col=p.color||'#1d6fb8';
        pop(e,'<h3>Bear '+(p.bear_id||'')+
              ' <span style=\\"display:inline-block;width:12px;height:12px;border-radius:50%;background:'+col+';vertical-align:middle\\"></span></h3>'+
              '<b>Time:</b> '+(p.timestamp||'')+'<br><b>Sex:</b> '+(p.sex||'')+
              '<br><b>Age:</b> '+(p.age||'')+'<br><b>Season:</b> '+(p.season||'')); }});
      map.on('mouseenter','cp-points',()=>map.getCanvas().style.cursor='pointer');
      map.on('mouseleave','cp-points',()=>map.getCanvas().style.cursor='');

      map.on('click','sim-points',(e)=>{{ const p=e.features[0].properties||{{}};
        const isReal = p.type==='real';
        const isAlt  = p.type==='alternative';
        const title  = isReal ? 'Real GPS step' : isAlt ? 'Simulated alternative' : 'Simulation';
        const col    = p.color||'#e8830c';
        let details  = '<b>Bear:</b> '+(p.bear_id||'')+'<br>';
        if (isReal) details += '<b>Time:</b> '+(p.timestamp||'')+'<br><b>Season:</b> '+(p.season||'')+'<br><b>Step length:</b> '+(p.length_m?Math.round(p.length_m)+' m':'')+'<br>';
        if (isAlt)  details += '<b>Step no.:</b> '+(p.step_idx||'')+'<br><b>Simulated length:</b> '+(p.length_m?Math.round(p.length_m)+' m':'')+'<br><b>Heading:</b> '+(p.angle?Math.round(p.angle)+' deg':'')+'<br>';
        pop(e,'<h3>'+title+' <span style=\\"display:inline-block;width:10px;height:10px;border-radius:50%;background:'+col+';vertical-align:middle\\"></span></h3>'+details); }});

      map.on('click','wolf-lynx-fill',(e)=>{{ const p=e.features[0].properties||{{}};
        const isWolf = (p.REFERENCESPECIESNAME||'').toLowerCase().includes('lupus') || p.species==='wolf';
        const title  = isWolf ? 'Wolf' : 'Lynx';
        pop(e,'<h3>'+title+' (BfN monitoring)</h3>'+
              '<b>Grid cell:</b> '+(p.ID_LOCALID||p.GmlID||'')+
              '<br><span style=\\"font-size:12px;color:#555\\">At least one confirmed record (C1/C2: genetics, '+
              'photo, track or kill) somewhere in this 10x10 km cell, not an exact position.</span>'+
              '<br><span style=\\"font-size:11px;color:#777\\">Source: geodienste.bfn.de, free to use</span>'); }});
      map.on('mouseenter','wolf-lynx-fill',()=>map.getCanvas().style.cursor='pointer');
      map.on('mouseleave','wolf-lynx-fill',()=>map.getCanvas().style.cursor='');

      map.on('click','gbif-bears-points',(e)=>{{ const p=e.features[0].properties||{{}};
        const link = p.gbif_url ? '<br><a href=\\"'+p.gbif_url+'\\" target=\\"_blank\\" rel=\\"noopener\\">View record on GBIF</a>' : '';
        const img = p.image_url ? '<br><img src=\\"'+p.image_url+'\\" style=\\"max-width:220px;max-height:160px;border-radius:6px;margin-top:6px;display:block\\" loading=\\"lazy\\" onerror=\\"this.style.display=\\'none\\'\\" />' : '';
        pop(e,'<h3>'+(p.scientific_name||'Ursus arctos')+'</h3>'+
              '<b>Country:</b> '+(p.country||'')+
              '<br><b>Date:</b> '+(p.event_date||'')+
              '<br><b>Source:</b> '+(p.institution||'')+link+img); }});
      map.on('mouseenter','gbif-bears-points',()=>map.getCanvas().style.cursor='pointer');
      map.on('mouseleave','gbif-bears-points',()=>map.getCanvas().style.cursor='');
    }}

    // -------------------------------------------------------
    // Bounds, toggles and base map change
    // -------------------------------------------------------
    // A coordinate counts as valid when it is not (0,0) or close to it.
    // Devices without GPS are stored as lat=0, lng=0 and would otherwise
    // widen fitBounds to a world view.
    function isValidCoord(c) {{
      return Math.abs(c[0]) > 0.01 || Math.abs(c[1]) > 0.01;
    }}

    function boundsOf(fcs) {{
      const b = new maplibregl.LngLatBounds(); let has = false;
      fcs.forEach(fc => {{
        (fc.features || []).forEach(f => {{
          const g = f.geometry; if (!g) return;
          if (g.type === 'Point') {{
            if (isValidCoord(g.coordinates)) {{ b.extend(g.coordinates); has = true; }}
          }}
          else if (g.type === 'LineString') {{
            g.coordinates.forEach(c => {{ if (isValidCoord(c)) {{ b.extend(c); has = true; }} }});
          }}
          else if (g.type === 'Polygon') {{
            g.coordinates.forEach(r => r.forEach(c => {{ if (isValidCoord(c)) {{ b.extend(c); has = true; }} }}));
          }}
          else if (g.type === 'MultiPolygon') {{
            g.coordinates.forEach(poly => poly.forEach(r => r.forEach(c => {{ if (isValidCoord(c)) {{ b.extend(c); has = true; }} }})));
          }}
        }});
      }});
      return has ? b : null;
    }}

    // Fixed zoom targets per subsystem (avoids fitBounds problems with (0,0) coordinates)
    const ZOOM_TARGETS = {{
      japan:      {{ center: [139.93, 37.48], zoom: 11 }},
      carpathian: {{ center: null, zoom: 8 }},   // dynamic via fitBounds (the data has valid coordinates)
      simulation: {{ center: null, zoom: 8 }},   // dynamic via fitBounds
      wolf_lynx:  {{ center: null, zoom: 6 }},   // dynamic, covers all of Germany
      gbif_bears: {{ center: null, zoom: 5 }}    // dynamic, covers DE and RO
    }};

    function navigateToGroup(groupKey) {{
      const g = GROUPS[groupKey];
      const t = ZOOM_TARGETS[groupKey];
      if (t.center) {{
        // Fixed target, for example Japan, so no fitBounds is needed
        map.flyTo({{ center: t.center, zoom: t.zoom, duration: 800 }});
      }} else {{
        // Dynamic: fitBounds derived from the data
        const b = boundsOf(g.fcs);
        if (b) map.fitBounds(b, {{ padding: 60, maxZoom: 12, duration: 800 }});
      }}
    }}

    function onToggle(groupKey, checked) {{
      const g = GROUPS[groupKey];
      setVis(g.layers, checked);
      if (checked) navigateToGroup(groupKey);
      saveStateToUrl();
    }}

    // -------------------------------------------------------
    // DRAWING: capture and save new markers and areas.
    //
    // MapLibre is embedded here through components.html(), that is, plain
    // HTML and JavaScript in an iframe, not as a true bidirectional
    // Streamlit component. Drawn data therefore cannot flow back to
    // Python as a return value. Instead, reusing the same principle as
    // saveStateToUrl() above but actively rather than passively, saving
    // writes the geometry into the URL and triggers a
    // REAL navigation (location.href rather than only
    // history.replaceState). That reloads the Streamlit page, Python
    // reads the new query parameters, stores them in the database and
    // removes the parameters again (see map.py).
    // -------------------------------------------------------
    const drawState = {{ mode: null, polygonPoints: [] }};

    function setDrawHint(text) {{ const h = document.getElementById('draw-hint'); if (h) h.textContent = text; }}

    function updateMarkerPreview(lngLat) {{
      const src = map.getSource('draw_marker_preview');
      if (!src) return;
      src.setData(lngLat
        ? {{ type:'FeatureCollection', features:[{{ type:'Feature', properties:{{}}, geometry:{{type:'Point', coordinates:[lngLat.lng, lngLat.lat]}} }}] }}
        : {{ type:'FeatureCollection', features:[] }});
    }}

    function updatePolygonPreview() {{
      const pts = drawState.polygonPoints;
      const pointFeatures = pts.map(p => ({{ type:'Feature', properties:{{}}, geometry:{{type:'Point', coordinates:p}} }}));
      const ptsSrc = map.getSource('draw_polygon_points');
      if (ptsSrc) ptsSrc.setData({{ type:'FeatureCollection', features:pointFeatures }});

      const polySrc = map.getSource('draw_polygon_preview');
      if (!polySrc) return;
      if (pts.length < 2) {{ polySrc.setData({{type:'FeatureCollection', features:[]}}); return; }}
      const ring = pts.length >= 3 ? [...pts, pts[0]] : pts; // close the ring only from 3 points on
      const geomType = pts.length >= 3 ? 'Polygon' : 'LineString';
      const coords = pts.length >= 3 ? [ring] : ring;
      polySrc.setData({{ type:'FeatureCollection', features:[{{ type:'Feature', properties:{{}}, geometry:{{type:geomType, coordinates:coords}} }}] }});
    }}

    function updateSaveButtonState() {{
      const saveBtn = document.getElementById('draw-save-btn');
      if (!saveBtn) return;
      if (drawState.mode === 'marker') {{
        saveBtn.disabled = !drawState.pendingMarker;
      }} else if (drawState.mode === 'polygon') {{
        const nameInput = document.getElementById('draw-name-input');
        saveBtn.disabled = drawState.polygonPoints.length < 3 || !(nameInput && nameInput.value.trim());
      }} else {{
        saveBtn.disabled = true;
      }}
    }}

    function resetDrawing(keepMode) {{
      drawState.polygonPoints = [];
      drawState.pendingMarker = null;
      updateMarkerPreview(null);
      updatePolygonPreview();
      const nameInput = document.getElementById('draw-name-input');
      if (nameInput) {{ nameInput.value = ''; nameInput.style.display = 'none'; }}
      document.getElementById('draw-undo-btn').style.display = 'none';
      document.getElementById('draw-cancel-btn').style.display = 'none';
      updateSaveButtonState();
      if (!keepMode) {{
        drawState.mode = null;
        document.getElementById('mode-marker').classList.remove('active');
        document.getElementById('mode-polygon').classList.remove('active');
        setDrawHint('Choose a mode, then click on the map.');
      }}
    }}

    function onMapClickForDrawing(e) {{
      if (drawState.mode === 'marker') {{
        drawState.pendingMarker = e.lngLat;
        updateMarkerPreview(e.lngLat);
        setDrawHint(`Point selected (${{e.lngLat.lat.toFixed(5)}}, ${{e.lngLat.lng.toFixed(5)}}). Save, or click again.`);
        document.getElementById('draw-cancel-btn').style.display = 'block';
        updateSaveButtonState();
      }} else if (drawState.mode === 'polygon') {{
        drawState.polygonPoints.push([e.lngLat.lng, e.lngLat.lat]);
        updatePolygonPreview();
        document.getElementById('draw-undo-btn').style.display = 'block';
        document.getElementById('draw-cancel-btn').style.display = 'block';
        const nameInput = document.getElementById('draw-name-input');
        if (drawState.polygonPoints.length >= 3) {{
          nameInput.style.display = 'block';
        }}
        setDrawHint(`${{drawState.polygonPoints.length}} point(s) placed` +
          (drawState.polygonPoints.length < 3 ? ' (at least 3 required).' : ' - enter a name, then save.'));
        updateSaveButtonState();
      }}
    }}

    function saveDrawing() {{
      try {{
        const parentWin = window.parent;
        const url = new URL(parentWin.location.href);
        if (drawState.mode === 'marker' && drawState.pendingMarker) {{
          url.searchParams.set('new_marker_lat', drawState.pendingMarker.lat.toFixed(6));
          url.searchParams.set('new_marker_lng', drawState.pendingMarker.lng.toFixed(6));
        }} else if (drawState.mode === 'polygon' && drawState.polygonPoints.length >= 3) {{
          const nameInput = document.getElementById('draw-name-input');
          url.searchParams.set('new_polygon_name', nameInput.value.trim());
          url.searchParams.set('new_polygon_coords', JSON.stringify(drawState.polygonPoints));
        }} else {{
          return;
        }}
        parentWin.location.href = url.toString(); // real navigation, triggers a Streamlit rerun
      }} catch (e) {{
        setDrawHint('Saving failed (cross-origin?). Reload the page manually and try again.');
      }}
    }}

    function wireDrawingControls() {{
      document.getElementById('mode-marker').addEventListener('click', () => {{
        resetDrawing(false);
        drawState.mode = 'marker';
        document.getElementById('mode-marker').classList.add('active');
        setDrawHint('Click on the map to choose the marker location.');
        map.getCanvas().style.cursor = 'crosshair';
      }});
      document.getElementById('mode-polygon').addEventListener('click', () => {{
        resetDrawing(false);
        drawState.mode = 'polygon';
        document.getElementById('mode-polygon').classList.add('active');
        setDrawHint('Click points for the area boundary (at least 3).');
        map.getCanvas().style.cursor = 'crosshair';
      }});
      document.getElementById('draw-undo-btn').addEventListener('click', () => {{
        drawState.polygonPoints.pop();
        updatePolygonPreview();
        if (drawState.polygonPoints.length < 3) document.getElementById('draw-name-input').style.display = 'none';
        setDrawHint(`${{drawState.polygonPoints.length}} point(s) placed.`);
        updateSaveButtonState();
      }});
      document.getElementById('draw-cancel-btn').addEventListener('click', () => {{
        resetDrawing(false);
        map.getCanvas().style.cursor = '';
      }});
      document.getElementById('draw-name-input').addEventListener('input', updateSaveButtonState);
      document.getElementById('draw-save-btn').addEventListener('click', saveDrawing);
      map.on('click', onMapClickForDrawing);
    }}

    function wireControls() {{
      const bind = (key) => {{
        const cb = document.getElementById(GROUPS[key].id);
        if (cb) cb.addEventListener('change', e => onToggle(key, e.target.checked));
      }};
      bind('japan'); bind('carpathian'); bind('simulation'); bind('wolf_lynx'); bind('gbif_bears');

      // -------------------------------------------------------
      // Base map change: calling map.once('style.load', ...) after every
      // setStyle() restores the layers only AFTER the style reset has
      // completed. diff:false forces a clean reset without a race.
      // -------------------------------------------------------
      const sel = document.getElementById('basemap-select');
      if (sel) sel.addEventListener('change', e => {{
        currentStyleName = e.target.value;
        map.setStyle(STYLES[e.target.value], {{ diff: false }});
        map.once('style.load', () => {{
          addSourcesAndLayers();
          applyVisibilityFromCheckboxes();
          // A style change removes terrain and hillshading, so restore
          // them here if 3D was active.
          if (terrain3d) applyTerrain(true);
        }});
        saveStateToUrl();
      }});

      const t3d = document.getElementById('toggle-3d');
      if (t3d) t3d.addEventListener('change', e => {{
        terrain3d = e.target.checked;
        applyTerrain(terrain3d);
        saveStateToUrl();
      }});

      // Continuously remember the camera position (pan and zoom),
      // debounced so it is not written on every drag frame.
      map.on('moveend', saveStateDebounced);
    }}

    // Initial start: map.on('load') fires exactly once
    map.on('load', () => {{
      addSourcesAndLayers();
      applyVisibilityFromCheckboxes();
      if (terrain3d) applyTerrain(true);   // restore the state from the URL
      wirePopups();
      wireControls();
      wireDrawingControls();

      // For layers that are already visible but whose data changed, for
      // example a different bear or period, fly to the new position.
      // Otherwise the camera would stay where the URL persistence put it,
      // in a place that holds no data for the newly selected filter.
      let didRefit = false;
      REFIT_ON_LOAD.forEach(key => {{
        const g = GROUPS[key];
        const cb = g ? document.getElementById(g.id) : null;
        if (cb && cb.checked) {{ navigateToGroup(key); didRefit = true; }}
      }});
      if (didRefit) saveStateToUrl();
    }});
  </script>
</body>
</html>
"""
    components.html(html, height=height, scrolling=False)