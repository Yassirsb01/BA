"""
japan_map_component.py
========================
Map component for the Japan experiment. One camera is selected, N
simulated bears start there at an actual photo event (place and time) and
move according to the Carpathian model (speed, optional terrain weighting
and directional persistence). Real photo times AT THAT CAMERA are drawn as
marks on the same timeline, for direct comparison with the simulated
bears.

There is no "entire period" time window as in the Carpathian animation:
the simulation has no natural end, so only fixed windows are offered
(15 minutes to 72 hours).

Built on the same, already tested logic as animation_component.py
(parseTime, interpolation, play/pause/step/scrub), extended to several
simultaneous bear tracks instead of one.

3D terrain: same controls and same failure behaviour as in
animation_component.py (elevation model, hillshading and camera pitch
behind a toggle; if the elevation data cannot be loaded the map stays
usable in 2D). It matters more here than for the Carpathian data: the
cameras of the Fukushima region stand in strongly structured terrain, and
whether a simulated bear crosses a slope or follows a valley cannot be
seen in a flat top-down view.
"""

import json
import streamlit as st
import streamlit.components.v1 as components

BASEMAP_STYLES = {
    "Satellite": {
        "version": 8,
        "sources": {"esri-imagery": {
            "type": "raster",
            "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
            "tileSize": 256, "maxzoom": 17, "attribution": "Tiles &copy; Esri",
        }},
        "layers": [{"id": "esri-imagery", "type": "raster", "source": "esri-imagery"}],
    },
    "Positron": "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
    "Liberty": "https://tiles.openfreemap.org/styles/liberty",
}

# Free elevation data without an API key (the source used by the
# official MapLibre 3D terrain example), identical to the source in
# animation_component.py so that both maps behave the same.
TERRAIN_TILEJSON = "https://tiles.mapterhorn.com/tilejson.json"

# Distinguishable colours for up to 20 simultaneous bears, reused cyclically
BEAR_COLORS = [
    "#1d6fb8", "#e8830c", "#2fa365", "#c0392b", "#8e44ad",
    "#16a085", "#d35400", "#2980b9", "#c2185b", "#7f8c8d",
]


def _empty_fc():
    return {"type": "FeatureCollection", "features": []}


def _path_to_geojson(path: list[dict]) -> dict:
    features = []
    for p in path:
        features.append({
            "type": "Feature",
            "properties": {"timestamp": p["time"].strftime("%Y-%m-%d %H:%M:%S")},
            "geometry": {"type": "Point", "coordinates": [p["lng"], p["lat"]]},
        })
    return {"type": "FeatureCollection", "features": features}


def render_japan_map(
    cameras: list[dict],
    start_camera: dict,
    bears: list[dict],
    real_events: list,
    basemap: str = "Satellite",
    detection_radius_m: float = 100,
    photo_counts: dict | None = None,
    height: int = 850,
):
    """
    Args:
        cameras: all camera locations {device_id, lat, lng}, for map
            context and for lighting up on approach.
        start_camera: the selected starting camera {device_id, lat, lng}.
        bears: output of
            japan_comparison.simulate_multiple_bears_from_sighting(), a
            list of {bear_index, gender, age, season, path}.
        real_events: list of datetime, the real photo times AT THE
            starting camera (from get_real_events_for_camera()), used for
            the timeline marks.
        photo_counts: {device_id: number of real photographs} from
            japan_comparison.get_photo_counts_by_camera(), or None if the
            database could not be reached.

            None and {} do NOT mean the same thing:
            None = photo counts unknown (no database connection)
            {}   = database reachable, but no photographs at any camera
            A MISSING key with a reachable database also means "zero
            photographs" rather than "unknown": the underlying query
            groups by device_id and simply omits cameras without
            recordings. Without this distinction, 10 of 20 cameras
            reported "no database connection" despite a working one.
    """
    counts_known = photo_counts is not None
    photo_counts = photo_counts or {}
    start_id = str(start_camera.get("device_id", ""))

    # The photo count travels along as a feature property so the popup
    # can show it without a second data source. -1 means exclusively
    # "unknown because there is no database connection"; 0 means
    # "demonstrably no photographs at this camera".
    cameras_geojson = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "properties": {
                 "device_id": c.get("device_id", "?"),
                 "lat": round(float(c["lat"]), 5),
                 "lng": round(float(c["lng"]), 5),
                 "photos": int(photo_counts.get(str(c.get("device_id")), 0))
                           if counts_known else -1,
                 "is_start": str(c.get("device_id")) == start_id,
             },
             "geometry": {"type": "Point", "coordinates": [c["lng"], c["lat"]]}}
            for c in cameras
        ],
    }

    bear_tracks_js = []
    for i, b in enumerate(bears):
        bear_tracks_js.append({
            "color": BEAR_COLORS[i % len(BEAR_COLORS)],
            "label": f"Bear {i + 1} ({b['gender']}/{b['age']}, {b['season']})",
            "path": _path_to_geojson(b["path"]),
        })

    real_events_js = [t.strftime("%Y-%m-%d %H:%M:%S") for t in real_events]

    styles_js = json.dumps(BASEMAP_STYLES)
    bm_options = "".join(
        f'<option value="{name}"{" selected" if name == basemap else ""}>{name}</option>'
        for name in BASEMAP_STYLES
    )

    n_bears = len(bears)
    status_note = (
        f"{n_bears} simulated bear(s) from camera {start_camera.get('device_id','?')} - "
        f"{len(real_events)} real photograph(s) known at this camera"
    )

    html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="initial-scale=1,maximum-scale=1,user-scalable=no" />
  <link href="https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.css" rel="stylesheet" />
  <script src="https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.js"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet" />
  <style>
    :root {{
      --bg:#e9e6e1; --ink:#1a1917; --ink-soft:#4a4741; --ink-faint:#8a8680;
      --panel:rgba(252,251,249,0.94); --line:rgba(18,17,15,.10); --line-strong:rgba(18,17,15,.13);
      --flash:#ffcb3d; --real-event:#c0392b;
    }}
    html, body {{ margin:0; padding:0; height:100%; background:var(--bg);
                  font-family:'IBM Plex Sans',system-ui,-apple-system,sans-serif; color:var(--ink); }}
    #map {{ position:absolute; inset:0; width:100%; height:{height}px; }}
    .wrap {{ position:relative; width:100%; height:{height}px; overflow:hidden; }}
    .mono {{ font-family:'IBM Plex Mono',monospace; }}
    .glass {{
      background:var(--panel); backdrop-filter:blur(16px); -webkit-backdrop-filter:blur(16px);
      box-shadow:0 1px 0 rgba(255,255,255,.7) inset, 0 6px 24px rgba(20,18,15,.13), 0 0 0 1px rgba(18,17,15,.08);
      border-radius:13px;
    }}

    .status-panel {{ position:absolute; top:16px; left:16px; width:250px; padding:14px 15px 13px; z-index:3; max-height:calc(100% - 200px); overflow-y:auto; }}
    .status-title {{ font-weight:600; font-size:13px; margin-bottom:4px; }}
    .status-note {{ font-size:10.5px; color:var(--ink-faint); line-height:1.4; margin-bottom:8px; }}
    .legend {{ display:grid; gap:5px; margin-top:6px; }}
    .legend-row {{ display:flex; align-items:center; gap:8px; font-size:11px; color:var(--ink-soft); }}
    .ldot {{ width:9px; height:9px; border-radius:50%; flex:none; }}
    .hr {{ height:1px; background:var(--line); margin:10px 0; }}
    .section-label {{ font-size:10px; letter-spacing:.07em; text-transform:uppercase; color:var(--ink-faint); margin-bottom:5px; }}
    #basemap-select {{ width:100%; font-size:12px; padding:6px 8px; border-radius:8px; border:1px solid var(--line-strong); background:#fff; }}
    .switch-row {{ display:flex; align-items:center; gap:8px; margin-top:9px; font-size:11.5px; color:var(--ink-soft); cursor:pointer; }}
    .switch-row input {{ accent-color:#1d6fb8; cursor:pointer; }}
    .terrain-note {{ font-size:10px; color:#b4553c; margin-top:6px; line-height:1.4; display:none; }}

    /* Kamera-Popup */
    .pop {{ font-family:'IBM Plex Sans',system-ui,sans-serif; color:var(--ink); }}
    .pop-title {{ font-weight:600; font-size:12.5px; margin-bottom:5px; }}
    .pop-row {{ font-size:11.5px; color:var(--ink-soft); margin-top:3px; }}
    .pop-mono {{ font-family:'IBM Plex Mono',monospace; font-size:10.5px; color:var(--ink-faint); }}
    .pop-muted {{ color:var(--ink-faint); font-style:italic; }}
    .pop-badge {{ display:inline-block; font-size:10px; padding:2px 6px; border-radius:5px;
                  background:rgba(255,203,61,.25); border:1px solid rgba(180,140,20,.35);
                  color:#7a5c05; margin-bottom:4px; }}
    .maplibregl-popup-content {{ padding:10px 12px; border-radius:10px;
                                 box-shadow:0 6px 24px rgba(20,18,15,.18); }}

    .log-panel {{ position:absolute; top:16px; right:16px; width:230px; max-height:340px;
                  padding:12px 13px; z-index:3; display:flex; flex-direction:column; }}
    .log-title {{ font-weight:600; font-size:12.5px; margin-bottom:8px; }}
    .log-list {{ overflow-y:auto; display:flex; flex-direction:column-reverse; gap:5px; }}
    .log-entry {{ font-size:10.5px; padding:5px 7px; border-radius:6px; background:rgba(232,131,12,.08);
                   border-left:2px solid var(--flash); color:var(--ink-soft); }}
    .log-empty {{ font-size:11px; color:var(--ink-faint); font-style:italic; }}

    .control-bar {{
      position:absolute; left:50%; transform:translateX(-50%); bottom:20px;
      width:min(820px, calc(100% - 32px)); z-index:4; padding:15px 18px 13px;
    }}
    .scrub-row {{ display:flex; align-items:center; gap:12px; margin-bottom:9px; }}
    .time-label {{ font-size:11px; color:var(--ink-faint); width:74px; flex:none; }}
    .time-label.right {{ text-align:right; }}
    .track {{ position:relative; flex:1; height:22px; display:flex; align-items:center; cursor:pointer; touch-action:none; }}
    .track-bg {{ position:absolute; left:0; right:0; height:5px; border-radius:3px; background:rgba(18,17,15,.10); }}
    .real-event-ticks {{ position:absolute; inset:0; pointer-events:none; }}
    .real-event-tick {{
      position:absolute; top:50%; width:2px; height:14px; margin-top:-7px;
      background:var(--real-event);
    }}
    .track-fill {{ position:absolute; left:0; height:5px; border-radius:3px; background:#8a8680; width:0%; }}
    .track-thumb {{ position:absolute; top:50%; width:15px; height:15px; margin-top:-7.5px; margin-left:-7.5px;
      border-radius:50%; background:#fff; box-shadow:0 1px 4px rgba(20,18,15,.28), 0 0 0 1px rgba(18,17,15,.10); left:0%; }}
    .real-event-legend {{ font-size:10px; color:var(--real-event); display:flex; align-items:center; gap:5px; margin-bottom:8px; }}
    .real-event-legend .swatch {{ width:10px; height:2px; background:var(--real-event); display:inline-block; }}

    .controls-row {{ display:flex; align-items:center; gap:14px; }}
    .btn-cluster {{ display:flex; align-items:center; gap:6px; }}
    .icon-btn {{ width:34px; height:34px; display:flex; align-items:center; justify-content:center;
      border:1px solid var(--line-strong); background:#fff; border-radius:9px; cursor:pointer; color:var(--ink); }}
    .icon-btn:hover {{ background:#f2efea; }}
    .play-btn {{ width:42px; height:42px; display:flex; align-items:center; justify-content:center;
      border:none; background:var(--ink); border-radius:11px; cursor:pointer; color:#fff;
      box-shadow:0 2px 8px rgba(20,18,15,.24); }}
    .play-btn:hover {{ background:#33302b; }}
    .divider {{ width:1px; height:30px; background:var(--line); }}
    .clock-block {{ display:flex; flex-direction:column; gap:1px; min-width:170px; }}
    .clock {{ font-size:19px; font-weight:500; line-height:1.1; }}
    .clock-sub {{ font-size:10.5px; color:var(--ink-faint); }}
    .right-controls {{ margin-left:auto; display:flex; align-items:center; gap:10px; }}
    .speed-pills {{ display:flex; gap:2px; padding:3px; border-radius:10px; background:rgba(18,17,15,.055); }}
    .speed-pill {{ border:none; cursor:pointer; font-family:'IBM Plex Mono',monospace; font-size:11.5px; font-weight:500;
      padding:6px 9px; border-radius:7px; background:transparent; color:var(--ink-faint); }}
    .speed-pill.active {{ background:#fff; color:var(--ink); box-shadow:0 1px 3px rgba(20,18,15,.16); }}
  </style>
</head>
<body>
  <div class="wrap">
    <div id="map"></div>

    <div class="status-panel glass">
      <div class="status-title">Japan experiment</div>
      <div class="status-note">{status_note}</div>
      <div class="legend" id="bear-legend"></div>
      <div class="hr"></div>
      <div class="section-label">Base map</div>
      <select id="basemap-select">{bm_options}</select>

      <label class="switch-row"><input type="checkbox" id="toggle-3d" /> 3D terrain (elevation model)</label>
      <div class="terrain-note" id="terrain-note">Elevation data unavailable; the map stays in 2D.</div>
    </div>

    <div class="log-panel glass">
      <div class="log-title">Trigger log (all cameras)</div>
      <div class="log-list" id="log-list"><div class="log-empty">No trigger yet</div></div>
    </div>

    <div class="control-bar glass">
      <div class="real-event-legend"><span class="swatch"></span> red marks = real photographs at this camera</div>
      <div class="scrub-row">
        <div class="time-label mono" id="start-label">–</div>
        <div class="track" id="track">
          <div class="track-bg"></div>
          <div class="real-event-ticks" id="real-event-ticks"></div>
          <div class="track-fill" id="track-fill"></div>
          <div class="track-thumb" id="track-thumb"></div>
        </div>
        <div class="time-label right mono" id="end-label">–</div>
      </div>
      <div class="controls-row">
        <div class="btn-cluster">
          <button id="step-back" class="icon-btn" title="One step back">
            <svg width="13" height="13" viewBox="0 0 12 12"><rect x="1" y="1.5" width="1.8" height="9" fill="currentColor"></rect><polygon points="11,1.5 11,10.5 4,6" fill="currentColor"></polygon></svg>
          </button>
          <button id="play-btn" class="play-btn" title="Play/Pause">
            <svg id="play-icon" width="13" height="13" viewBox="0 0 12 12"><polygon points="2.5,1.2 11,6 2.5,10.8" fill="currentColor"></polygon></svg>
          </button>
          <button id="step-fwd" class="icon-btn" title="One step forward">
            <svg width="13" height="13" viewBox="0 0 12 12"><polygon points="1,1.5 1,10.5 8,6" fill="currentColor"></polygon><rect x="9.2" y="1.5" width="1.8" height="9" fill="currentColor"></rect></svg>
          </button>
          <button id="reset-btn" class="icon-btn" title="Reset" style="font-size:15px;">&#8634;</button>
        </div>
        <div class="divider"></div>
        <div class="clock-block">
          <div class="clock mono" id="clock-label">–</div>
          <div class="clock-sub" id="clock-sub">–</div>
        </div>
        <div class="right-controls">
          <div class="speed-pills" id="speed-pills"></div>
        </div>
      </div>
    </div>
  </div>

  <script>
    const STYLES = {styles_js};
    const DATA = {{
      cameras: {json.dumps(cameras_geojson)},
      bearTracks: {json.dumps(bear_tracks_js)},
      realEvents: {json.dumps(real_events_js)},
      detectionRadiusM: {detection_radius_m}
    }};

    const startCamCoords = [{start_camera["lng"]}, {start_camera["lat"]}];

    const TERRAIN_TILEJSON = "{TERRAIN_TILEJSON}";

    const map = new maplibregl.Map({{
      container:'map', style:STYLES["{basemap}"], center:startCamCoords, zoom:13,
      maxPitch:85,   // without this the camera cannot be pitched into the 3D view
      attributionControl:false,
    }});
    // visualizePitch shows the pitch in the compass; otherwise it is hard
    // to tell which inclination the view is currently at.
    map.addControl(new maplibregl.NavigationControl({{ visualizePitch:true }}), 'top-right');
    map.addControl(new maplibregl.ScaleControl({{maxWidth:110, unit:'metric'}}), 'bottom-right');

    // -------------------------------------------------------
    // Sources and layers: cameras plus one marker/trail pair PER bear
    // -------------------------------------------------------
    function addSourcesAndLayers() {{
      const addSrc = (id, d) => {{ if (!map.getSource(id)) map.addSource(id, {{type:'geojson', data:d}}); }};
      const addLayerSafe = (spec) => {{ if (!map.getLayer(spec.id)) map.addLayer(spec); }};

      if (!map.getSource('terrain-dem')) {{
        try {{ map.addSource('terrain-dem', {{ type:'raster-dem', url:TERRAIN_TILEJSON }}); }}
        catch (e) {{ console.warn('Terrain source unavailable:', e); }}
      }}

      // Hillshading uses the same elevation model as the 3D mode and
      // makes slope direction and landform visible. It is toggled
      // together with 3D and sits BELOW all data layers so that cameras
      // and bear paths stay readable.
      if (map.getSource('terrain-dem')) {{
        addLayerSafe({{ id:'hillshade', type:'hillshade', source:'terrain-dem',
          layout:{{ visibility:'none' }},
          paint:{{ 'hillshade-exaggeration':0.45, 'hillshade-shadow-color':'#3b3226' }} }});
      }}

      addSrc('cameras', DATA.cameras);
      addLayerSafe({{ id:'cameras-halo', type:'circle', source:'cameras',
        paint:{{ 'circle-radius': ['case', ['boolean', ['feature-state','active'], false], 16, 0],
                 'circle-color': '#ffcb3d', 'circle-opacity': 0.35 }} }});
      addLayerSafe({{ id:'cameras', type:'circle', source:'cameras',
        paint:{{ 'circle-radius': ['case', ['boolean', ['feature-state','active'], false], 8, 5],
                 'circle-color': ['case', ['boolean', ['feature-state','active'], false], '#ffcb3d', '#8a8680'],
                 'circle-stroke-width': 1.5, 'circle-stroke-color': '#fff' }} }});

      DATA.bearTracks.forEach((bt, i) => {{
        addSrc('trail-'+i, {{type:'FeatureCollection', features:[]}});
        addSrc('marker-'+i, {{type:'FeatureCollection', features:[]}});
        addLayerSafe({{ id:'trail-'+i, type:'line', source:'trail-'+i,
          paint:{{'line-color':bt.color, 'line-width':3, 'line-opacity':0.85}} }});
        addLayerSafe({{ id:'marker-halo-'+i, type:'circle', source:'marker-'+i,
          paint:{{'circle-radius':11, 'circle-color':bt.color, 'circle-opacity':0.25}} }});
        addLayerSafe({{ id:'marker-'+i, type:'circle', source:'marker-'+i,
          paint:{{'circle-radius':6, 'circle-color':bt.color, 'circle-stroke-width':2, 'circle-stroke-color':'#fff'}} }});
      }});

      // A base map change removes terrain and hillshading, so restore
      // them here if 3D was active.
      if (uiState.terrain3d) applyTerrain(true);
    }}

    // -------------------------------------------------------
    // 3D terrain, taken from animation_component.py with the same
    // controls and the same failure behaviour: if the elevation data
    // fails to load, the map stays fully usable in 2D and the toggle
    // resets itself with a note.
    // -------------------------------------------------------
    const uiState = {{ terrain3d:false }};

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
      uiState.terrain3d = false;
    }}

    // Report missing elevation tiles without blocking the map
    map.on('error', (e) => {{
      const msg = (e && e.error && e.error.message) || '';
      if (uiState.terrain3d && /terrain|dem|mapterhorn/i.test(msg)) showTerrainNote();
    }});

    // -------------------------------------------------------
    // Camera popups
    //
    // Popups rather than permanent labels: with 20 cameras, some only a
    // few hundred metres apart, permanent labels overlap when zoomed out
    // and cover exactly the bear paths of interest. When a camera lights
    // up during the animation, one click is enough to identify it.
    // -------------------------------------------------------
    function wireCameraPopups() {{
      map.on('click', 'cameras', (e) => {{
        const f = e.features && e.features[0];
        if (!f) return;
        const p = f.properties || {{}};

        // Three cases are distinguished: unknown (-1, no database
        // connection), demonstrably no photographs (0), and a real count.
        const nPhotos = Number(p.photos);
        let photoLine;
        if (nPhotos < 0) {{
          photoLine = '<div class="pop-row pop-muted">Photo count unknown (no database connection)</div>';
        }} else if (nPhotos === 0) {{
          photoLine = '<div class="pop-row pop-muted">No photographs at this camera</div>';
        }} else {{
          photoLine = '<div class="pop-row"><b>' + nPhotos + '</b> real photograph(s) at this camera</div>';
        }}

        const startLine = (p.is_start === true || p.is_start === 'true')
          ? '<div class="pop-badge">Starting camera of this simulation</div>' : '';

        new maplibregl.Popup({{ offset: 12, closeButton: true, maxWidth: '260px' }})
          .setLngLat(f.geometry.coordinates)
          .setHTML(
            '<div class="pop">' +
              '<div class="pop-title">Camera ' + (p.device_id || '?') + '</div>' +
              startLine +
              '<div class="pop-row pop-mono">' + p.lat + ', ' + p.lng + '</div>' +
              photoLine +
            '</div>'
          )
          .addTo(map);
      }});

      // Pointer cursor so that the markers are recognisably clickable
      map.on('mouseenter', 'cameras', () => {{ map.getCanvas().style.cursor = 'pointer'; }});
      map.on('mouseleave', 'cameras', () => {{ map.getCanvas().style.cursor = ''; }});
    }}

    function fitToData() {{
      const coords = [];
      DATA.cameras.features.forEach(f => coords.push(f.geometry.coordinates));
      DATA.bearTracks.forEach(bt => bt.path.features.forEach(f => coords.push(f.geometry.coordinates)));
      if (!coords.length) return;
      let minLng=Infinity,minLat=Infinity,maxLng=-Infinity,maxLat=-Infinity;
      coords.forEach(([lng,lat]) => {{
        minLng=Math.min(minLng,lng); maxLng=Math.max(maxLng,lng);
        minLat=Math.min(minLat,lat); maxLat=Math.max(maxLat,lat);
      }});
      map.fitBounds([[minLng,minLat],[maxLng,maxLat]], {{padding:100, maxZoom:16, duration:0}});
    }}

    function wireBasemapControl() {{
      const sel = document.getElementById('basemap-select');
      if (sel) sel.addEventListener('change', e => {{
        map.setStyle(STYLES[e.target.value], {{diff:false}});
        map.once('style.load', () => {{ addSourcesAndLayers(); renderFrame(); }});
      }});

      const t3d = document.getElementById('toggle-3d');
      if (t3d) t3d.addEventListener('change', e => {{
        uiState.terrain3d = e.target.checked;
        applyTerrain(uiState.terrain3d);
      }});
    }}

    function renderLegend() {{
      const c = document.getElementById('bear-legend'); if (!c) return;
      c.innerHTML = DATA.bearTracks.map(bt =>
        `<div class="legend-row"><span class="ldot" style="background:${{bt.color}}"></span>${{bt.label}}</div>`
      ).join('');
    }}

    // -------------------------------------------------------
    // Animation engine (multi-bear variant)
    // -------------------------------------------------------
    const SPEEDS = [1, 10, 60, 300, 1000];
    const animState = {{
      playing:false, speed:60, tracks:[], startTime:null, endTime:null, currentTime:null,
      rafId:null, lastWallClock:null, activeCameraIds:new Set(), loggedDetections:[],
      lastRenderWall:0,   // throttling of the geometry updates, see animLoop()
      initialDetectionFrame:true,
    }};

    function parseTime(v) {{ return v ? Date.parse(String(v).replace(' ','T')) : NaN; }}

    function buildTracks() {{
      return DATA.bearTracks.map(bt => {{
        const points = [];
        (bt.path.features || []).forEach(f => {{
          const t = parseTime(f.properties.timestamp);
          if (isNaN(t)) return;
          points.push({{t, lng:f.geometry.coordinates[0], lat:f.geometry.coordinates[1]}});
        }});
        points.sort((a,b)=>a.t-b.t);
        return {{color: bt.color, label: bt.label, points}};
      }});
    }}

    function haversine(lat1,lng1,lat2,lng2) {{
      const R=6371000, toRad=d=>d*Math.PI/180;
      const dLat=toRad(lat2-lat1), dLng=toRad(lng2-lng1);
      const a=Math.sin(dLat/2)**2 + Math.cos(toRad(lat1))*Math.cos(toRad(lat2))*Math.sin(dLng/2)**2;
      return 2*R*Math.asin(Math.sqrt(a));
    }}

    function interpolatePosition(track, t) {{
      if (!track.length) return null;
      if (t < track[0].t) return null;
      if (t >= track[track.length-1].t) return track[track.length-1];
      let lo=0, hi=track.length-1;
      while (hi-lo>1) {{ const mid=(lo+hi)>>1; if (track[mid].t<=t) lo=mid; else hi=mid; }}
      const a=track[lo], b=track[hi];
      const frac = b.t===a.t ? 0 : (t-a.t)/(b.t-a.t);
      return {{lng:a.lng+(b.lng-a.lng)*frac, lat:a.lat+(b.lat-a.lat)*frac}};
    }}

    function trailCoords(track, t) {{
      const coords = [];
      for (const p of track) {{ if (p.t >= t) break; coords.push([p.lng, p.lat]); }}
      const cur = interpolatePosition(track, t);
      if (cur) coords.push([cur.lng, cur.lat]);
      return coords;
    }}

    function fmtClock(t) {{ return new Date(t).toLocaleTimeString('en-GB', {{hour:'2-digit', minute:'2-digit'}}); }}
    function fmtDate(t) {{ return new Date(t).toLocaleDateString('en-GB', {{day:'2-digit', month:'2-digit', year:'numeric'}}); }}

    function updateCameraFlashAndLog(t) {{
      const ignoreInitial = animState.initialDetectionFrame;
      const nowActive = new Set();
      const newLogEntries = [];
      animState.tracks.forEach(tr => {{
        const pos = interpolatePosition(tr.points, t);
        if (!pos) return;
        DATA.cameras.features.forEach(f => {{
          const [clng, clat] = f.geometry.coordinates;
          if (haversine(pos.lat, pos.lng, clat, clng) <= DATA.detectionRadiusM) {{
            nowActive.add(f.properties.device_id);
          }}
        }});
      }});
      DATA.cameras.features.forEach(f => {{
        const id = f.properties.device_id;
        const shouldBeActive = nowActive.has(id);
        const wasActive = animState.activeCameraIds.has(id);
        if (shouldBeActive !== wasActive) {{
          map.setFeatureState({{source:'cameras', id: f.id}}, {{active: shouldBeActive}});
          if (shouldBeActive && !ignoreInitial) {{
            const timeStr = fmtClock(t);
            animState.loggedDetections.unshift(`${{timeStr}} Uhr &middot; Kamera ${{id}}`);
          }}
        }}
      }});
      animState.activeCameraIds = nowActive;
      animState.initialDetectionFrame = false;

      const list = document.getElementById('log-list');
      if (list) {{
        list.innerHTML = animState.loggedDetections.length
          ? animState.loggedDetections.slice(0, 40).map(e => `<div class="log-entry">${{e}}</div>`).join('')
          : '<div class="log-empty">No trigger yet</div>';
      }}
    }}

    function renderFrame() {{
      animState.tracks.forEach((tr, i) => {{
        const pos = interpolatePosition(tr.points, animState.currentTime);
        const markerFeatures = pos ? [{{type:'Feature', properties:{{}}, geometry:{{type:'Point', coordinates:[pos.lng,pos.lat]}}}}] : [];
        const trailC = trailCoords(tr.points, animState.currentTime);
        const trailFeatures = trailC.length>=2 ? [{{type:'Feature', properties:{{}}, geometry:{{type:'LineString', coordinates:trailC}}}}] : [];
        const ms = map.getSource('marker-'+i); if (ms) ms.setData({{type:'FeatureCollection', features:markerFeatures}});
        const ts = map.getSource('trail-'+i); if (ts) ts.setData({{type:'FeatureCollection', features:trailFeatures}});
      }});

      updateCameraFlashAndLog(animState.currentTime);

      const span = Math.max(1, animState.endTime - animState.startTime);
      const pct = Math.max(0, Math.min(100, (animState.currentTime-animState.startTime)/span*100));
      const fill = document.getElementById('track-fill'); if (fill) fill.style.width = pct+'%';
      const thumb = document.getElementById('track-thumb'); if (thumb) thumb.style.left = pct+'%';

      const clockEl = document.getElementById('clock-label'); if (clockEl) clockEl.textContent = fmtClock(animState.currentTime);
      const clockSub = document.getElementById('clock-sub');
      if (clockSub) clockSub.textContent = fmtDate(animState.currentTime);

      const playIcon = document.getElementById('play-icon');
      if (playIcon) playIcon.innerHTML = animState.playing
        ? '<rect x="2" y="1.5" width="3" height="9" rx="0.8" fill="currentColor"></rect><rect x="7" y="1.5" width="3" height="9" rx="0.8" fill="currentColor"></rect>'
        : '<polygon points="2.5,1.2 11,6 2.5,10.8" fill="currentColor"></polygon>';
    }}

    function renderRealEventTicks() {{
      const container = document.getElementById('real-event-ticks');
      if (!container) return;
      container.innerHTML = '';
      const span = Math.max(1, animState.endTime - animState.startTime);
      (DATA.realEvents || []).forEach(ts => {{
        const t = parseTime(ts);
        if (isNaN(t) || t < animState.startTime || t > animState.endTime) return;
        const pct = (t - animState.startTime) / span * 100;
        const tick = document.createElement('div');
        tick.className = 'real-event-tick';
        tick.style.left = pct + '%';
        tick.title = new Date(t).toLocaleString('en-GB');
        container.appendChild(tick);
      }});
    }}

    // Shortest gap between two geometry updates, in milliseconds.
    // renderFrame() replaces two sources PER BEAR, so the cost grows with
    // the number of simulated bears, and every replacement makes MapLibre
    // redraw. With the 3D terrain switched on that redraw also covers the
    // elevation mesh and the hillshade. At the display refresh rate of 60
    // frames per second the browser cannot keep up and the animation
    // stutters.
    // Limiting the updates to 30 per second, and to 20 with terrain,
    // keeps the motion smooth to the eye. The clock keeps advancing on
    // every frame, so no position is skipped: only the number of
    // intermediate pictures is reduced.
    const RENDER_GAP_MS_FLAT = 33;
    const RENDER_GAP_MS_TERRAIN = 50;

    function animLoop(nowWall) {{
      if (!animState.playing) return;
      if (animState.lastWallClock==null) animState.lastWallClock = nowWall;
      const dtSec = (nowWall-animState.lastWallClock)/1000;
      animState.lastWallClock = nowWall;
      animState.currentTime += dtSec * animState.speed * 60 * 1000;
      if (animState.currentTime >= animState.endTime) {{
        animState.currentTime = animState.endTime; renderFrame(); pauseAnimation(); return;
      }}
      const gap = uiState.terrain3d ? RENDER_GAP_MS_TERRAIN : RENDER_GAP_MS_FLAT;
      if (nowWall - animState.lastRenderWall >= gap) {{
        animState.lastRenderWall = nowWall;
        renderFrame();
      }}
      animState.rafId = requestAnimationFrame(animLoop);
    }}

    function playAnimation() {{
      if (animState.playing || animState.startTime==null) return;
      if (animState.currentTime >= animState.endTime) {{
        animState.currentTime = animState.startTime;
        animState.loggedDetections = [];
        animState.activeCameraIds = new Set();
        animState.initialDetectionFrame = true;
      }}
      animState.playing = true; animState.lastWallClock = null;
      renderFrame();
      animState.rafId = requestAnimationFrame(animLoop);
    }}
    function pauseAnimation() {{
      if (!animState.playing) return;
      animState.playing = false;
      if (animState.rafId) cancelAnimationFrame(animState.rafId);
      renderFrame();
    }}
    function stepAnimation(dir) {{
      if (animState.startTime==null) return;
      const allTimes = new Set();
      animState.tracks.forEach(tr => tr.points.forEach(p => allTimes.add(p.t)));
      const times = Array.from(allTimes).sort((a,b)=>a-b);
      if (!times.length) return;
      let next;
      if (dir>0) {{ next = times.find(t=>t>animState.currentTime); if (next==null) next = animState.endTime; }}
      else {{ const past = times.filter(t=>t<animState.currentTime); next = past.length ? past[past.length-1] : animState.startTime; }}
      animState.currentTime = Math.max(animState.startTime, Math.min(animState.endTime, next));
      renderFrame();
    }}
    function scrubFromClientX(clientX) {{
      const el = document.getElementById('track'); if (!el || animState.startTime==null) return;
      const r = el.getBoundingClientRect();
      const pct = Math.max(0, Math.min(1, (clientX-r.left)/r.width));
      pauseAnimation();
      animState.currentTime = animState.startTime + pct*(animState.endTime-animState.startTime);
      renderFrame();
    }}

    function renderSpeedPills() {{
      const c = document.getElementById('speed-pills'); if (!c) return;
      c.innerHTML = '';
      SPEEDS.forEach(v => {{
        const b = document.createElement('button');
        b.className = 'speed-pill' + (v===animState.speed ? ' active' : '');
        b.textContent = v+'×';
        b.addEventListener('click', () => {{ animState.speed=v; renderSpeedPills(); }});
        c.appendChild(b);
      }});
    }}

    function initAnimation() {{
      animState.tracks = buildTracks();
      let minT = Infinity, maxT = -Infinity;
      animState.tracks.forEach(tr => {{
        if (tr.points.length) {{
          minT = Math.min(minT, tr.points[0].t);
          maxT = Math.max(maxT, tr.points[tr.points.length-1].t);
        }}
      }});
      if (!isFinite(minT)) return false;
      animState.startTime = minT; animState.endTime = maxT; animState.currentTime = minT;

      const sl = document.getElementById('start-label'); if (sl) sl.textContent = fmtClock(minT);
      const el = document.getElementById('end-label'); if (el) el.textContent = fmtClock(maxT);
      renderRealEventTicks();
      renderLegend();
      renderSpeedPills();
      renderFrame();
      return true;
    }}

    function wireControls() {{
      document.getElementById('play-btn').addEventListener('click', () => animState.playing ? pauseAnimation() : playAnimation());
      document.getElementById('step-fwd').addEventListener('click', () => {{ pauseAnimation(); stepAnimation(1); }});
      document.getElementById('step-back').addEventListener('click', () => {{ pauseAnimation(); stepAnimation(-1); }});
      document.getElementById('reset-btn').addEventListener('click', () => {{
        pauseAnimation();
        if (animState.startTime!=null) {{
          animState.currentTime = animState.startTime;
          animState.loggedDetections = [];
          animState.activeCameraIds = new Set();
          animState.initialDetectionFrame = true;
          renderFrame();
        }}
      }});
      const track = document.getElementById('track');
      track.addEventListener('pointerdown', e => {{
        scrubFromClientX(e.clientX);
        const move = ev => scrubFromClientX(ev.clientX);
        const up = () => {{ window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); }};
        window.addEventListener('pointermove', move);
        window.addEventListener('pointerup', up);
      }});
    }}

    map.on('load', () => {{
      DATA.cameras.features.forEach((f, i) => {{ f.id = i; }});
      addSourcesAndLayers();
      fitToData();
      wireBasemapControl();
      wireCameraPopups();   // bound to the map, not the layer, so it survives style changes
      wireControls();
      initAnimation();
    }});
  </script>
</body>
</html>
"""
    components.html(html, height=height, scrolling=False)