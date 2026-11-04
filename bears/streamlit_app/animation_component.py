"""
animation_component.py
========================
Standalone MapLibre map for the movement animation of the Carpathian
bears: the real GPS route together with the matching candidate steps from
the movement model (see sync_simulation.py), guaranteed to be the same
bear, the same day and the same timestamps.

Designed as an analysis tool, so that it is possible to follow WHERE and
WHEN a bear moved and how plausible the simulated alternatives are.

Display:
  - Blue dot with a growing trail: the REAL GPS movement, interpolated
    between fixes. The full path is NOT drawn in advance by default,
    which would reveal the result before playback, but can be shown with
    a toggle.
  - Orange dots and trails: the SIMULATED bears moving in step with the
    real one (sync_simulation.build_synced_geojson()["simulated"]).
    Several are shown deliberately, because each path is only ONE random
    draw from the model and not a prediction. The spread between the
    lines is the actual statement: it shows how large the space of
    possibilities is for an identical starting point.
  - Grey fan (can be switched off): at EVERY real step, all N candidate
    moves the model generated at that point in time. This is not a path
    of its own; the alternatives are N independent options PER step, that
    is, the space of possibilities of a SINGLE step, whereas the orange
    trails show what that becomes over many steps.

Base maps:
  - Satellite (Esri World Imagery) for terrain context, the same source
    already used by carpathian_bears.py
  - Positron, Liberty and Dark as vector alternatives
  - Optional 3D mode: elevation model (Mapterhorn, free and without an
    API key, the source used by the official MapLibre 3D example) plus
    camera pitch. Deliberately opt-in because it requires additional
    network tiles; on failure the map stays usable in 2D and a note is
    shown in the panel.
"""

import json
import streamlit as st
import streamlit.components.v1 as components

# In remote areas such as the Carpathians, Esri World Imagery only
# provides about 1 m resolution, roughly zoom level 17. With a higher
# maxzoom, MapLibre requests tiles that do not exist there and Esri
# responds with the placeholder tile "Map data not yet available". With
# maxzoom set correctly, MapLibre upscales the existing tiles instead:
# slightly blurrier, but always an image.
ESRI_NATIVE_MAXZOOM = 17

_ESRI_IMAGERY_SOURCE = {
    "type": "raster",
    "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
    "tileSize": 256,
    "maxzoom": ESRI_NATIVE_MAXZOOM,
    "attribution": "Satellite imagery: Esri, Vantor, Earthstar Geographics and the GIS User Community",
}

# Transparent label and boundary layer, to keep orientation on satellite
# imagery (place names, administrative boundaries).
_ESRI_REFERENCE_SOURCE = {
    "type": "raster",
    "tiles": ["https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"],
    "tileSize": 256,
    "maxzoom": ESRI_NATIVE_MAXZOOM,
    "attribution": "Labels: Esri, HERE, Garmin, &copy; OpenStreetMap contributors and the GIS User Community",
}

_SATELLITE_STYLE = {
    "version": 8,
    "sources": {"esri-imagery": _ESRI_IMAGERY_SOURCE},
    "layers": [{"id": "esri-imagery", "type": "raster", "source": "esri-imagery"}],
}

_SATELLITE_LABELS_STYLE = {
    "version": 8,
    "sources": {"esri-imagery": _ESRI_IMAGERY_SOURCE, "esri-reference": _ESRI_REFERENCE_SOURCE},
    "layers": [
        {"id": "esri-imagery", "type": "raster", "source": "esri-imagery"},
        {"id": "esri-reference", "type": "raster", "source": "esri-reference"},
    ],
}

BASEMAP_STYLES = {
    "Satellite": _SATELLITE_STYLE,
    "Satellite + labels": _SATELLITE_LABELS_STYLE,
    "Positron": "https://tiles.openfreemap.org/styles/positron",
    "Liberty": "https://tiles.openfreemap.org/styles/liberty",
    "Dark": "https://tiles.openfreemap.org/styles/dark",
}

# Slightly above the native resolution, to allow closer zoom without the
# upscaling becoming unusably blurry.
MAP_MAX_ZOOM = 18.5

# Free elevation data without an API key (the source used by the
# official MapLibre 3D terrain example).
TERRAIN_TILEJSON = "https://tiles.mapterhorn.com/tilejson.json"

# Colours of the simulated realisations. All kept in the orange range,
# which stands for "the model", but distinguishable in lightness so that
# a single line can be followed through the animation. Reused cyclically
# if more realisations are supplied.
SIM_COLORS = ["#e8830c", "#a8541a", "#f5b942", "#c96a0f", "#8a4513"]


def _empty_fc():
    return {"type": "FeatureCollection", "features": []}


def render_animation_map(
    carpathian: dict | None = None,
    alternatives: dict | None = None,
    simulated: dict | None = None,
    basemap: str = "Satellite",
    bear_label: str = "",
    dataset_label: str = "Carpathian Bears - GPS tracking (Romania)",
    source_label: str = "",
    height: int = 900,
):
    """
    Args:
        carpathian: {"points": GeoJSON, "paths": GeoJSON}, the real GPS
            route of ONE bear on ONE day at full resolution.
        alternatives: GeoJSON FeatureCollection of the candidate steps
            (from sync_simulation.build_synced_geojson()["alternative"]).
        simulated: GeoJSON FeatureCollection of the continuous simulated
            paths (from build_synced_geojson()["simulated"]). The points
            carry properties.realization (0..n-1) and the same
            properties.timestamp as the real route, which forces the real
            and simulated bears to move in step. None or empty means only
            the real bear is animated.
        bear_label: for example "BEAR 7", shown at the top right of the
            panel.
        dataset_label: which dataset is displayed, for readers opening the
            map without prior knowledge.
        source_label: where the data comes from, for example
            "MariaDB (ursus)".
    """
    carpathian = carpathian or {}
    cp_points = carpathian.get("points", _empty_fc())
    cp_paths = carpathian.get("paths", _empty_fc())
    alt_points = alternatives or _empty_fc()
    sim_points = simulated or _empty_fc()

    styles_js = json.dumps(BASEMAP_STYLES)
    bm_options = "".join(
        f'<option value="{name}"{" selected" if name == basemap else ""}>{name}</option>'
        for name in BASEMAP_STYLES
    )

    data = {
        "cp_points": json.dumps(cp_points),
        "cp_paths": json.dumps(cp_paths),
        "alt_points": json.dumps(alt_points),
        "sim_points": json.dumps(sim_points),
    }

    n_points_label = f"{len(cp_points.get('features', []))} Pkt."
    n_alts_label = f"{len(alt_points.get('features', []))} Kand."

    n_realizations = len({
        f.get("properties", {}).get("realization", 0)
        for f in sim_points.get("features", [])
    })
    n_sims_label = f"{n_realizations} runs" if n_realizations else "-"

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
      --blue:#1d6fb8; --orange:#e8830c; --fan:#8a8680;
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

    .status-panel {{ position:absolute; top:16px; left:16px; width:264px; padding:14px 15px 13px; z-index:3; }}
    .status-top {{ display:flex; align-items:baseline; justify-content:space-between; gap:8px; }}
    .status-title {{ font-size:13px; font-weight:600; letter-spacing:-0.01em; }}
    .status-tag {{ font-size:10px; color:var(--ink-faint); }}
    .dataset {{ margin-top:3px; font-size:10.5px; color:var(--ink-faint); line-height:1.4; }}
    .source-badge {{
      display:inline-flex; align-items:center; gap:5px; margin-top:7px;
      font-family:'IBM Plex Mono',monospace; font-size:9.5px; color:var(--ink-soft);
      background:rgba(18,17,15,.05); padding:3px 7px; border-radius:6px;
    }}
    .source-dot {{ width:5px; height:5px; border-radius:50%; background:#3aa76d; }}
    .legend {{ margin-top:10px; display:grid; gap:7px; }}
    .legend-row {{ display:flex; align-items:center; gap:8px; }}
    .ldot {{ width:9px; height:9px; border-radius:50%; flex:none; }}
    .ltext {{ font-size:11.5px; color:var(--ink-soft); }}
    .lcount {{ margin-left:auto; font-size:11px; color:var(--ink-faint); }}
    .hr {{ height:1px; background:var(--line); margin:12px 0 10px; }}
    /* Note that the simulated paths are random draws, placed directly
       below the legend rather than only in the documentation. */
    .sim-note {{
      margin-top:10px; padding:7px 9px; border-radius:7px;
      background:rgba(232,131,12,.09); border:1px solid rgba(232,131,12,.22);
      font-size:10px; line-height:1.45; color:var(--ink-soft);
    }}
    .section-label {{ font-size:10px; letter-spacing:.07em; text-transform:uppercase; color:var(--ink-faint); margin-bottom:5px; }}
    #basemap-select {{
      width:100%; appearance:none; font-family:inherit; font-size:12px; color:var(--ink);
      padding:7px 9px; border-radius:8px; border:1px solid var(--line-strong); background:#fff; cursor:pointer;
    }}
    .switch-row {{ display:flex; align-items:center; gap:8px; margin-top:9px; font-size:11.5px; color:var(--ink-soft); cursor:pointer; }}
    .switch-row input {{ accent-color:var(--blue); cursor:pointer; }}
    .terrain-note {{ font-size:10px; color:#b4553c; margin-top:6px; line-height:1.4; display:none; }}

    .control-bar {{
      position:absolute; left:50%; transform:translateX(-50%); bottom:20px;
      width:min(880px, calc(100% - 32px)); z-index:4; padding:15px 18px 13px;
    }}
    .scrub-row {{ display:flex; align-items:center; gap:12px; margin-bottom:13px; }}
    .time-label {{ font-size:11px; color:var(--ink-faint); width:74px; flex:none; }}
    .time-label.right {{ text-align:right; }}
    .track {{ position:relative; flex:1; height:22px; display:flex; align-items:center; cursor:pointer; touch-action:none; }}
    .track-bg {{ position:absolute; left:0; right:0; height:5px; border-radius:3px; background:rgba(18,17,15,.10); }}
    .ticks {{ position:absolute; inset:0; }}
    .tick {{ position:absolute; top:50%; width:1px; height:9px; margin-top:-4.5px; background:rgba(18,17,15,.18); }}
    .track-fill {{ position:absolute; left:0; height:5px; border-radius:3px; background:var(--blue); width:0%; }}
    .track-thumb {{
      position:absolute; top:50%; width:15px; height:15px; margin-top:-7.5px; margin-left:-7.5px;
      border-radius:50%; background:#fff; box-shadow:0 1px 4px rgba(20,18,15,.28), 0 0 0 1px rgba(18,17,15,.10); left:0%;
    }}
    .controls-row {{ display:flex; align-items:center; gap:14px; }}
    .btn-cluster {{ display:flex; align-items:center; gap:6px; }}
    .icon-btn {{
      width:34px; height:34px; display:flex; align-items:center; justify-content:center;
      border:1px solid var(--line-strong); background:#fff; border-radius:9px; cursor:pointer; color:var(--ink);
    }}
    .icon-btn:hover {{ background:#f2efea; }}
    .play-btn {{
      width:42px; height:42px; display:flex; align-items:center; justify-content:center;
      border:none; background:var(--ink); border-radius:11px; cursor:pointer; color:#fff;
      box-shadow:0 2px 8px rgba(20,18,15,.24);
    }}
    .play-btn:hover {{ background:#33302b; }}
    .divider {{ width:1px; height:34px; background:var(--line); }}
    .clock-block {{ display:flex; flex-direction:column; gap:1px; min-width:170px; }}
    .clock {{ font-size:19px; font-weight:500; letter-spacing:-0.01em; line-height:1.1; }}
    .clock-sub {{ font-size:10.5px; color:var(--ink-faint); }}
    .metrics {{ display:flex; gap:14px; }}
    .metric-val {{ font-family:'IBM Plex Mono',monospace; font-size:13px; font-weight:500; line-height:1.2; }}
    .metric-lbl {{ font-size:9.5px; letter-spacing:.05em; text-transform:uppercase; color:var(--ink-faint); }}
    .right-controls {{ margin-left:auto; display:flex; align-items:center; gap:10px; }}
    .speed-pills {{ display:flex; align-items:center; gap:2px; padding:3px; border-radius:10px; background:rgba(18,17,15,.055); }}
    .speed-pill {{
      border:none; cursor:pointer; font-family:'IBM Plex Mono',monospace; font-size:11.5px; font-weight:500;
      padding:6px 9px; border-radius:7px; background:transparent; color:var(--ink-faint);
    }}
    .speed-pill.active {{ background:#fff; color:var(--ink); box-shadow:0 1px 3px rgba(20,18,15,.16); }}
    .range-btn {{
      display:flex; align-items:center; gap:7px; height:34px; padding:0 12px;
      border:1px solid var(--line-strong); background:#fff; border-radius:9px; cursor:pointer;
      font-family:inherit; font-size:12px; color:var(--ink);
    }}
    .range-btn:hover, .range-btn.open {{ background:#f2efea; }}
    .rdot {{ width:6px; height:6px; border-radius:50%; background:var(--blue); }}
    .range-popover {{
      position:absolute; right:18px; bottom:calc(100% + 10px); width:300px; padding:15px 16px 16px;
      border-radius:13px; background:rgba(252,251,249,0.97); backdrop-filter:blur(18px);
      box-shadow:0 10px 34px rgba(20,18,15,.18), 0 0 0 1px rgba(18,17,15,.08); display:none;
    }}
    .popover-title {{ font-size:12.5px; font-weight:600; margin-bottom:12px; }}
    #anim-start {{
      width:100%; box-sizing:border-box; font-family:'IBM Plex Mono',monospace; font-size:12px;
      padding:7px 9px; border-radius:8px; border:1px solid var(--line-strong); background:#fff; color:var(--ink);
    }}
    .duration-pills {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:6px; }}
    .duration-pill {{
      border:1px solid var(--line-strong); cursor:pointer; font-family:inherit; font-size:11.5px;
      padding:6px 11px; border-radius:8px; background:#fff; color:var(--ink-soft);
    }}
    .duration-pill.active {{ background:var(--ink); color:#fff; border-color:var(--ink); }}
    .range-detail {{
      margin-top:13px; padding-top:11px; border-top:1px solid var(--line);
      font-family:'IBM Plex Mono',monospace; font-size:10.5px; color:var(--ink-faint); line-height:1.5;
    }}
    .hint-caption {{
      position:absolute; left:16px; bottom:20px; z-index:3;
      font-family:'IBM Plex Mono',monospace; font-size:10px; color:#7d7972;
      background:rgba(252,251,249,.8); padding:4px 8px; border-radius:6px;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div id="map"></div>

    <div class="status-panel glass">
      <div class="status-top">
        <div class="status-title">Movement animation</div>
        <div class="status-tag mono">{bear_label}</div>
      </div>
      <div class="dataset">{dataset_label}</div>
      <div class="source-badge"><span class="source-dot"></span>{source_label}</div>

      <div class="legend">
        <div class="legend-row">
          <span class="ldot" style="background:var(--blue); box-shadow:0 0 0 3px rgba(29,111,184,.16)"></span>
          <span class="ltext">Real GPS route</span>
          <span class="lcount mono">{n_points_label}</span>
        </div>
        <div class="legend-row">
          <span class="ldot" style="background:var(--orange); box-shadow:0 0 0 3px rgba(232,131,12,.16)"></span>
          <span class="ltext">Simulated bears</span>
          <span class="lcount mono">{n_sims_label}</span>
        </div>
        <div class="legend-row">
          <span class="ldot" style="background:var(--fan)"></span>
          <span class="ltext">Alternatives (fan)</span>
          <span class="lcount mono">{n_alts_label}</span>
        </div>
      </div>

      <div class="sim-note">
        Each orange path is <b>one possible realisation</b> of the model,
        not a prediction. Another run yields different paths; the spread
        between them is what matters, not any single line.
      </div>

      <div class="hr"></div>
      <div class="section-label">Base map</div>
      <select id="basemap-select">{bm_options}</select>

      <label class="switch-row"><input type="checkbox" id="toggle-3d" /> 3D terrain (elevation model)</label>
      <label class="switch-row"><input type="checkbox" id="toggle-fullpath" /> Show full path</label>
      <label class="switch-row"><input type="checkbox" id="toggle-sim" checked /> Simulated bears</label>
      <label class="switch-row"><input type="checkbox" id="toggle-fan" checked /> Alternatives fan</label>
      <div class="terrain-note" id="terrain-note">Elevation data unavailable; the map stays in 2D.</div>
    </div>

    <div class="control-bar glass">
      <div class="scrub-row">
        <div class="time-label mono" id="start-label">–</div>
        <div class="track" id="track">
          <div class="track-bg"></div>
          <div class="ticks" id="ticks"></div>
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

        <div class="divider"></div>

        <div class="metrics">
          <div>
            <div class="metric-val" id="metric-dist">–</div>
            <div class="metric-lbl">Distance</div>
          </div>
          <div>
            <div class="metric-val" id="metric-speed">–</div>
            <div class="metric-lbl">Speed</div>
          </div>
          <div title="Mean distance between the real bear and the simulated bears at the current time">
            <div class="metric-val" id="metric-sep">–</div>
            <div class="metric-lbl">Mean gap</div>
          </div>
        </div>

        <div class="right-controls">
          <div class="speed-pills" id="speed-pills"></div>
          <button id="range-toggle" class="range-btn">
            <span class="rdot"></span><span id="range-label">Entire period</span>
          </button>
        </div>
      </div>

      <div class="range-popover" id="range-popover">
        <div class="popover-title">Time range</div>
        <div class="section-label">Start time</div>
        <input type="datetime-local" id="anim-start" />
        <div class="section-label" style="margin-top:13px">Duration</div>
        <div class="duration-pills" id="duration-pills"></div>
        <div class="range-detail" id="range-detail">–</div>
      </div>
    </div>

    <div class="hint-caption" id="anim-hint"></div>
  </div>

  <script>
    const STYLES = {styles_js};
    const TERRAIN_TILEJSON = "{TERRAIN_TILEJSON}";
    const DATA = {{
      cp_points:  {data["cp_points"]},
      cp_paths:   {data["cp_paths"]},
      alt_points: {data["alt_points"]},
      sim_points: {data["sim_points"]}
    }};
    const SIM_COLORS = {json.dumps(SIM_COLORS)};

    const map = new maplibregl.Map({{
      container:'map', style:STYLES["{basemap}"], center:[25.3,45.6], zoom:8,
      maxPitch:85, maxZoom:{MAP_MAX_ZOOM},
      // Attribution is mandatory for Esri imagery, shown collapsed
      attributionControl:{{ compact:true }},
    }});
    map.addControl(new maplibregl.NavigationControl({{ visualizePitch:true }}), 'top-right');
    map.addControl(new maplibregl.ScaleControl({{ maxWidth:110, unit:'metric' }}), 'bottom-right');

    // -------------------------------------------------------
    // Sources and layers, recreated after every base map change
    // -------------------------------------------------------
    function addSourcesAndLayers() {{
      const addSrc = (id, d) => {{ if (!map.getSource(id)) map.addSource(id, {{ type:'geojson', data:d }}); }};
      addSrc('cp_paths_static', DATA.cp_paths);
      addSrc('anim-trail', {{ type:'FeatureCollection', features:[] }});
      addSrc('anim-marker', {{ type:'FeatureCollection', features:[] }});
      addSrc('alt-fan', {{ type:'FeatureCollection', features:[] }});
      addSrc('alt-fan-lines', {{ type:'FeatureCollection', features:[] }});
      addSrc('sim-trail', {{ type:'FeatureCollection', features:[] }});
      addSrc('sim-marker', {{ type:'FeatureCollection', features:[] }});

      if (!map.getSource('terrain-dem')) {{
        try {{ map.addSource('terrain-dem', {{ type:'raster-dem', url:TERRAIN_TILEJSON }}); }}
        catch (e) {{ console.warn('Terrain source unavailable:', e); }}
      }}

      const addLayerSafe = (spec) => {{ if (!map.getLayer(spec.id)) map.addLayer(spec); }};

      // Hillshading uses the same elevation model as the 3D mode and
      // makes slope direction and landform visible, which is often hard
      // to read on imagery alone. It is toggled together with 3D and sits
      // BELOW all data layers so route and fan stay readable.
      if (map.getSource('terrain-dem')) {{
        addLayerSafe({{ id:'hillshade', type:'hillshade', source:'terrain-dem',
          layout:{{ visibility:'none' }},
          paint:{{ 'hillshade-exaggeration':0.45, 'hillshade-shadow-color':'#3b3226' }} }});
      }}

      // Full path: off by default, otherwise the result would be visible
      // before playback. Can be shown with the toggle.
      addLayerSafe({{ id:'cp-paths-static', type:'line', source:'cp_paths_static',
        layout:{{ visibility:'none' }},
        paint:{{ 'line-color':'#1d6fb8','line-width':2,'line-opacity':0.35,'line-dasharray':[2,2] }} }});

      // The fan is neutral grey rather than orange: orange now marks the
      // simulated bears moving along, and otherwise the two depictions of
      // the simulation could not be told apart.
      addLayerSafe({{ id:'alt-fan-lines', type:'line', source:'alt-fan-lines',
        paint:{{ 'line-color':'#8a8680','line-width':1.1,'line-opacity':0.42,'line-dasharray':[1,1.5] }} }});
      addLayerSafe({{ id:'alt-fan', type:'circle', source:'alt-fan',
        paint:{{ 'circle-radius':4,'circle-color':'#8a8680','circle-opacity':0.65,
                 'circle-stroke-width':1,'circle-stroke-color':'#fff' }} }});

      // Simulated bears sit BELOW the real bear so the blue reference
      // stays readable where paths cross. The colour comes per feature
      // from properties.color (one realisation, one colour), so a single
      // layer covers any number of runs.
      addLayerSafe({{ id:'sim-trail', type:'line', source:'sim-trail',
        paint:{{ 'line-color':['get','color'],'line-width':2.4,'line-opacity':0.85 }} }});
      addLayerSafe({{ id:'sim-marker-halo', type:'circle', source:'sim-marker',
        paint:{{ 'circle-radius':10,'circle-color':['get','color'],'circle-opacity':0.22 }} }});
      addLayerSafe({{ id:'sim-marker', type:'circle', source:'sim-marker',
        paint:{{ 'circle-radius':5,'circle-color':['get','color'],
                 'circle-stroke-width':2,'circle-stroke-color':'#fff' }} }});

      addLayerSafe({{ id:'anim-trail', type:'line', source:'anim-trail',
        paint:{{ 'line-color':'#1d6fb8','line-width':3.5,'line-opacity':0.95 }} }});
      addLayerSafe({{ id:'anim-marker-halo', type:'circle', source:'anim-marker',
        paint:{{ 'circle-radius':13,'circle-color':'#1d6fb8','circle-opacity':0.25 }} }});
      addLayerSafe({{ id:'anim-marker', type:'circle', source:'anim-marker',
        paint:{{ 'circle-radius':6.5,'circle-color':'#1d6fb8','circle-stroke-width':2.5,'circle-stroke-color':'#fff' }} }});

      applyFullPathVisibility();
      applyLayerToggles();
      if (uiState.terrain3d) applyTerrain(true);
    }}

    function fitToData() {{
      const coords = [];
      // Include the simulated paths as well: they deliberately move away
      // from the real route and would otherwise leave the viewport.
      [DATA.cp_points, DATA.sim_points].forEach(fc => {{
        ((fc && fc.features) || []).forEach(f => {{
          const c = f.geometry && f.geometry.coordinates;
          if (c && isFinite(c[0]) && isFinite(c[1])) coords.push(c);
        }});
      }});
      if (!coords.length) return;
      let minLng=Infinity,minLat=Infinity,maxLng=-Infinity,maxLat=-Infinity;
      coords.forEach(([lng,lat]) => {{
        minLng=Math.min(minLng,lng); maxLng=Math.max(maxLng,lng);
        minLat=Math.min(minLat,lat); maxLat=Math.max(maxLat,lat);
      }});
      map.fitBounds([[minLng,minLat],[maxLng,maxLat]], {{ padding:110, maxZoom:15, duration:0 }});
    }}

    // -------------------------------------------------------
    // Base map style, 3D terrain and full path
    // -------------------------------------------------------
    const uiState = {{ terrain3d:false, fullPath:false, showSim:true, showFan:true }};

    function applyFullPathVisibility() {{
      if (map.getLayer('cp-paths-static')) {{
        map.setLayoutProperty('cp-paths-static','visibility', uiState.fullPath ? 'visible' : 'none');
      }}
    }}

    // Simulated bears and the fan can be toggled separately: shown
    // together over many steps the picture becomes cluttered, and
    // depending on the question only one of the two is of interest.
    function applyLayerToggles() {{
      const set = (id, on) => {{
        if (map.getLayer(id)) map.setLayoutProperty(id,'visibility', on ? 'visible' : 'none');
      }};
      set('sim-trail', uiState.showSim);
      set('sim-marker', uiState.showSim);
      set('sim-marker-halo', uiState.showSim);
      set('alt-fan', uiState.showFan);
      set('alt-fan-lines', uiState.showFan);
    }}

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

    function wireMapControls() {{
      const sel = document.getElementById('basemap-select');
      if (sel) sel.addEventListener('change', e => {{
        map.setStyle(STYLES[e.target.value], {{ diff:false }});
        map.once('style.load', () => {{ addSourcesAndLayers(); renderAnimationFrame(); }});
      }});

      const t3d = document.getElementById('toggle-3d');
      if (t3d) t3d.addEventListener('change', e => {{
        uiState.terrain3d = e.target.checked;
        applyTerrain(uiState.terrain3d);
      }});

      const tfp = document.getElementById('toggle-fullpath');
      if (tfp) tfp.addEventListener('change', e => {{
        uiState.fullPath = e.target.checked;
        applyFullPathVisibility();
      }});

      const tsim = document.getElementById('toggle-sim');
      if (tsim) tsim.addEventListener('change', e => {{
        uiState.showSim = e.target.checked;
        applyLayerToggles();
      }});

      const tfan = document.getElementById('toggle-fan');
      if (tfan) tfan.addEventListener('change', e => {{
        uiState.showFan = e.target.checked;
        applyLayerToggles();
      }});
    }}

    // -------------------------------------------------------
    // ANIMATION ENGINE
    // -------------------------------------------------------
    const SPEEDS = [1, 10, 60, 300, 1000];
    const DURATIONS = [[0.25,'15 min'],[0.5,'30 min'],[1,'1 h'],[4,'4 h'],[24,'24 h'],[-1,'Entire period']];

    const animState = {{
      playing:false, speed:300, track:[], altFan:{{steps:[], bySteptime:{{}}}},
      simTracks:[],   // one {{color, points:[{{t,lng,lat}}]}} per realisation
      startTime:null, endTime:null, currentTime:null, durHours:-1,
      rafId:null, lastWallClock:null,
      // Throttling of the geometry updates, see animLoop(). lastFanStepTime
      // remembers which step the alternative fan currently shows, so its
      // points are only rewritten when the step actually changes.
      lastRenderWall:0, lastFanStepTime:undefined,
    }};

    function parseTime(v) {{ return v ? Date.parse(String(v).replace(' ','T')) : NaN; }}

    // Haversine distance in metres, used for distance and speed readouts
    function haversine(a, b) {{
      const R = 6371000, toRad = d => d * Math.PI / 180;
      const dLat = toRad(b.lat - a.lat), dLng = toRad(b.lng - a.lng);
      const s = Math.sin(dLat/2)**2 + Math.cos(toRad(a.lat))*Math.cos(toRad(b.lat))*Math.sin(dLng/2)**2;
      return 2 * R * Math.asin(Math.sqrt(s));
    }}

    function buildTrackFromCarpathian() {{
      const points = [];
      (DATA.cp_points.features || []).forEach(f => {{
        const p = f.properties || {{}};
        const t = parseTime(p.timestamp);
        if (isNaN(t)) return;
        points.push({{ t, lng:f.geometry.coordinates[0], lat:f.geometry.coordinates[1] }});
      }});
      points.sort((a,b)=>a.t-b.t);
      return points;
    }}

    // Group simulated points by realisation. The structure matches the
    // real track so that interpolatePosition() and trailCoords() work for
    // the simulated bears without any special case.
    function buildSimTracks() {{
      const byRealization = {{}};
      (DATA.sim_points.features || []).forEach(f => {{
        const p = f.properties || {{}};
        const t = parseTime(p.timestamp);
        if (isNaN(t)) return;
        const r = p.realization == null ? 0 : p.realization;
        (byRealization[r] = byRealization[r] || []).push({{
          t, lng:f.geometry.coordinates[0], lat:f.geometry.coordinates[1]
        }});
      }});
      return Object.keys(byRealization).map(Number).sort((a,b)=>a-b).map((r, i) => {{
        const points = byRealization[r].sort((a,b)=>a.t-b.t);
        return {{ color: SIM_COLORS[i % SIM_COLORS.length], points }};
      }});
    }}

    function buildAlternativeFan() {{
      const bySteptime = {{}};
      (DATA.alt_points.features || []).forEach(f => {{
        const p = f.properties || {{}};
        const t = parseTime(p.timestamp);
        if (isNaN(t)) return;
        (bySteptime[t] = bySteptime[t] || []).push([f.geometry.coordinates[0], f.geometry.coordinates[1]]);
      }});
      return {{ steps: Object.keys(bySteptime).map(Number).sort((a,b)=>a-b), bySteptime }};
    }}

    function interpolatePosition(track, t) {{
      if (!track || !track.length) return null;
      if (t < track[0].t) return null;
      if (t >= track[track.length-1].t) return track[track.length-1];
      let lo=0, hi=track.length-1;
      while (hi-lo>1) {{ const mid=(lo+hi)>>1; if (track[mid].t<=t) lo=mid; else hi=mid; }}
      const a=track[lo], b=track[hi];
      const frac = b.t===a.t ? 0 : (t-a.t)/(b.t-a.t);
      return {{ lng:a.lng+(b.lng-a.lng)*frac, lat:a.lat+(b.lat-a.lat)*frac }};
    }}

    function trailCoords(track, t) {{
      const coords = [];
      for (const p of track) {{ if (p.t >= t) break; coords.push([p.lng, p.lat]); }}
      const cur = interpolatePosition(track, t);
      if (cur) coords.push([cur.lng, cur.lat]);
      return coords;
    }}

    function currentFanStepTime(t) {{
      const steps = animState.altFan.steps;
      if (!steps.length) return null;
      let chosen = steps[0];
      for (const s of steps) {{ if (s <= t) chosen = s; else break; }}
      return chosen;
    }}

    // Distance covered up to t, within the selected time window only
    function distanceUntil(track, t) {{
      let total = 0, prev = null;
      for (const p of track) {{
        if (p.t < animState.startTime) continue;
        if (p.t > t) break;
        if (prev) total += haversine(prev, p);
        prev = p;
      }}
      const cur = interpolatePosition(track, t);
      if (prev && cur) total += haversine(prev, cur);
      return total;
    }}

    // Instantaneous speed derived from the GPS step currently in progress
    function currentStepSpeedKmh(track, t) {{
      if (track.length < 2) return null;
      for (let i = 0; i < track.length - 1; i++) {{
        if (t >= track[i].t && t <= track[i+1].t) {{
          const dtH = (track[i+1].t - track[i].t) / 3600000;
          if (dtH <= 0) return null;
          return (haversine(track[i], track[i+1]) / 1000) / dtH;
        }}
      }}
      return null;
    }}

    function fmtClock(t) {{ return new Date(t).toLocaleTimeString('en-GB', {{ hour:'2-digit', minute:'2-digit' }}); }}
    function fmtDate(t)  {{ return new Date(t).toLocaleDateString('en-GB', {{ day:'2-digit', month:'2-digit', year:'numeric' }}); }}

    function renderAnimationFrame() {{
      const pos = interpolatePosition(animState.track, animState.currentTime);
      const markerFeatures = pos ? [{{ type:'Feature', properties:{{}}, geometry:{{type:'Point', coordinates:[pos.lng,pos.lat]}} }}] : [];
      const trailC = trailCoords(animState.track, animState.currentTime);
      const trailFeatures = trailC.length >= 2 ? [{{ type:'Feature', properties:{{}}, geometry:{{type:'LineString', coordinates:trailC}} }}] : [];

      const ms = map.getSource('anim-marker'); if (ms) ms.setData({{type:'FeatureCollection', features:markerFeatures}});
      const ts = map.getSource('anim-trail');  if (ts) ts.setData({{type:'FeatureCollection', features:trailFeatures}});

      // Simulated bears use exactly the same time logic as the real
      // bear, just N times over. The colour travels as a feature property
      // so that a single layer can draw all realisations.
      const simMarkers = [], simTrails = [];
      let sumSep = 0, nSep = 0;
      animState.simTracks.forEach(st => {{
        const sp = interpolatePosition(st.points, animState.currentTime);
        if (sp) {{
          simMarkers.push({{ type:'Feature', properties:{{color:st.color}},
            geometry:{{type:'Point', coordinates:[sp.lng, sp.lat]}} }});
          if (pos) {{ sumSep += haversine(pos, sp); nSep++; }}
        }}
        const c = trailCoords(st.points, animState.currentTime);
        if (c.length >= 2) simTrails.push({{ type:'Feature', properties:{{color:st.color}},
          geometry:{{type:'LineString', coordinates:c}} }});
      }});
      const sms = map.getSource('sim-marker'); if (sms) sms.setData({{type:'FeatureCollection', features:simMarkers}});
      const sts = map.getSource('sim-trail');  if (sts) sts.setData({{type:'FeatureCollection', features:simTrails}});

      const stepTime = currentFanStepTime(animState.currentTime);
      const fanCoords = stepTime != null ? (animState.altFan.bySteptime[stepTime] || []) : [];
      // The endpoints of the fan belong to the step, not to the moment,
      // so they only have to be rewritten when the step changes. The
      // connecting lines start at the moving bear and are updated every
      // time.
      if (stepTime !== animState.lastFanStepTime) {{
        animState.lastFanStepTime = stepTime;
        const fanFeatures = fanCoords.map(c => ({{ type:'Feature', properties:{{}}, geometry:{{type:'Point', coordinates:c}} }}));
        const fs = map.getSource('alt-fan'); if (fs) fs.setData({{type:'FeatureCollection', features:fanFeatures}});
      }}
      const fanLines = (pos && fanCoords.length) ? fanCoords.map(c => ({{
        type:'Feature', properties:{{}}, geometry:{{type:'LineString', coordinates:[[pos.lng,pos.lat], c]}}
      }})) : [];
      const fl = map.getSource('alt-fan-lines'); if (fl) fl.setData({{type:'FeatureCollection', features:fanLines}});

      const span = Math.max(1, animState.endTime - animState.startTime);
      const pct = Math.max(0, Math.min(100, (animState.currentTime - animState.startTime)/span*100));
      const fill = document.getElementById('track-fill'); if (fill) fill.style.width = pct + '%';
      const thumb = document.getElementById('track-thumb'); if (thumb) thumb.style.left = pct + '%';

      const clockEl = document.getElementById('clock-label');
      if (clockEl) clockEl.textContent = fmtClock(animState.currentTime);
      const clockSub = document.getElementById('clock-sub');
      if (clockSub) {{
        const idx = animState.track.filter(p => p.t <= animState.currentTime).length;
        clockSub.textContent = fmtDate(animState.currentTime) + ' · Step ' + Math.max(1, idx) + '/' + animState.track.length;
      }}

      const distEl = document.getElementById('metric-dist');
      if (distEl) {{
        const m = distanceUntil(animState.track, animState.currentTime);
        distEl.textContent = m >= 1000 ? (m/1000).toFixed(2) + ' km' : Math.round(m) + ' m';
      }}
      const spdEl = document.getElementById('metric-speed');
      if (spdEl) {{
        const kmh = currentStepSpeedKmh(animState.track, animState.currentTime);
        spdEl.textContent = kmh == null ? '–' : kmh.toFixed(2) + ' km/h';
      }}
      // How far is the model from reality at this moment? This turns the
      // visual comparison into a readable number. The gap should grow
      // over time because the simulation is never pulled back towards the
      // real route.
      const sepEl = document.getElementById('metric-sep');
      if (sepEl) {{
        if (!nSep) sepEl.textContent = '–';
        else {{
          const m = sumSep / nSep;
          sepEl.textContent = m >= 1000 ? (m/1000).toFixed(2) + ' km' : Math.round(m) + ' m';
        }}
      }}

      const playIcon = document.getElementById('play-icon');
      if (playIcon) {{
        playIcon.innerHTML = animState.playing
          ? '<rect x="2" y="1.5" width="3" height="9" rx="0.8" fill="currentColor"></rect><rect x="7" y="1.5" width="3" height="9" rx="0.8" fill="currentColor"></rect>'
          : '<polygon points="2.5,1.2 11,6 2.5,10.8" fill="currentColor"></polygon>';
      }}
    }}

    function renderTicksAndLabels() {{
      const container = document.getElementById('ticks');
      if (container) {{
        container.innerHTML = '';
        const span = Math.max(1, animState.endTime - animState.startTime);
        animState.track.filter(p => p.t >= animState.startTime && p.t <= animState.endTime).forEach(p => {{
          const tick = document.createElement('div');
          tick.className = 'tick';
          tick.style.left = ((p.t - animState.startTime)/span*100) + '%';
          container.appendChild(tick);
        }});
      }}
      const sl = document.getElementById('start-label'); if (sl) sl.textContent = fmtClock(animState.startTime);
      const el = document.getElementById('end-label');   if (el) el.textContent = fmtClock(animState.endTime);
      const rl = document.getElementById('range-label');
      if (rl) {{
        const d = DURATIONS.find(([v]) => v === animState.durHours);
        rl.textContent = d ? d[1] : (animState.durHours + ' h');
      }}
      const rd = document.getElementById('range-detail');
      if (rd) {{
        const inRange = animState.track.filter(p => p.t >= animState.startTime && p.t <= animState.endTime).length;
        rd.textContent = inRange + ' GPS points in range, ' + fmtClock(animState.startTime) + '-' + fmtClock(animState.endTime);
      }}
    }}

    function renderSpeedPills() {{
      const c = document.getElementById('speed-pills'); if (!c) return;
      c.innerHTML = '';
      SPEEDS.forEach(v => {{
        const b = document.createElement('button');
        b.className = 'speed-pill' + (v === animState.speed ? ' active' : '');
        b.textContent = v + '×';
        b.addEventListener('click', () => {{ animState.speed = v; renderSpeedPills(); }});
        c.appendChild(b);
      }});
    }}

    function renderDurationPills() {{
      const c = document.getElementById('duration-pills'); if (!c) return;
      c.innerHTML = '';
      DURATIONS.forEach(([v, label]) => {{
        const b = document.createElement('button');
        b.className = 'duration-pill' + (v === animState.durHours ? ' active' : '');
        b.textContent = label;
        b.addEventListener('click', () => {{ applyRange(animState.startTime, v); renderDurationPills(); }});
        c.appendChild(b);
      }});
    }}

    // Shortest gap between two geometry updates, in milliseconds.
    // Every call to renderAnimationFrame() replaces the data of six
    // sources, and each of those makes MapLibre redraw. With the 3D
    // terrain switched on that redraw also covers the elevation mesh and
    // the hillshade, which is far more expensive than the flat view. At
    // the display refresh rate of 60 frames per second the browser cannot
    // keep up and the animation stutters.
    // Limiting the updates to 30 per second, and to 20 with terrain,
    // keeps the motion smooth to the eye while cutting the work roughly
    // in half, or by two thirds. The clock keeps advancing on every
    // frame, so the animation neither slows down nor skips positions:
    // only the number of intermediate pictures is reduced.
    const RENDER_GAP_MS_FLAT = 33;
    const RENDER_GAP_MS_TERRAIN = 50;

    function animLoop(nowWall) {{
      if (!animState.playing) return;
      if (animState.lastWallClock == null) animState.lastWallClock = nowWall;
      const dtSec = (nowWall - animState.lastWallClock)/1000;
      animState.lastWallClock = nowWall;
      animState.currentTime += dtSec * animState.speed * 60 * 1000;
      if (animState.currentTime >= animState.endTime) {{
        animState.currentTime = animState.endTime;
        renderAnimationFrame(); pauseAnimation(); return;
      }}
      const gap = uiState.terrain3d ? RENDER_GAP_MS_TERRAIN : RENDER_GAP_MS_FLAT;
      if (nowWall - animState.lastRenderWall >= gap) {{
        animState.lastRenderWall = nowWall;
        renderAnimationFrame();
      }}
      animState.rafId = requestAnimationFrame(animLoop);
    }}

    function playAnimation() {{
      if (animState.playing || animState.startTime == null) return;
      if (animState.currentTime >= animState.endTime) animState.currentTime = animState.startTime;
      animState.playing = true; animState.lastWallClock = null;
      renderAnimationFrame();
      animState.rafId = requestAnimationFrame(animLoop);
    }}

    function pauseAnimation() {{
      if (!animState.playing) return;
      animState.playing = false;
      if (animState.rafId) cancelAnimationFrame(animState.rafId);
      renderAnimationFrame();
    }}

    function stepAnimation(dir) {{
      if (animState.startTime == null) return;
      const times = animState.track.map(p => p.t);
      if (!times.length) return;
      let next;
      if (dir > 0) {{ next = times.find(t => t > animState.currentTime); if (next == null) next = animState.endTime; }}
      else {{ const past = times.filter(t => t < animState.currentTime); next = past.length ? past[past.length-1] : animState.startTime; }}
      animState.currentTime = Math.max(animState.startTime, Math.min(animState.endTime, next));
      renderAnimationFrame();
    }}

    function applyRange(startTime, durHours) {{
      pauseAnimation();
      const maxT = animState.track.length ? animState.track[animState.track.length-1].t : startTime;
      animState.startTime = startTime;
      animState.endTime = durHours < 0 ? maxT : Math.min(maxT, startTime + durHours*3600*1000);
      animState.durHours = durHours;
      animState.currentTime = startTime;
      renderTicksAndLabels();
      renderAnimationFrame();
    }}

    function scrubFromClientX(clientX) {{
      const el = document.getElementById('track');
      if (!el || animState.startTime == null) return;
      const r = el.getBoundingClientRect();
      const pct = Math.max(0, Math.min(1, (clientX - r.left)/r.width));
      pauseAnimation();
      animState.currentTime = animState.startTime + pct * (animState.endTime - animState.startTime);
      renderAnimationFrame();
    }}

    function initAnimation() {{
      animState.track = buildTrackFromCarpathian();
      animState.altFan = buildAlternativeFan();
      animState.simTracks = buildSimTracks();

      const hint = document.getElementById('anim-hint');
      if (!animState.track.length) {{
        if (hint) hint.textContent = 'No time-stamped GPS data loaded.';
        return false;
      }}

      const minT = animState.track[0].t;
      applyRange(minT, animState.durHours);

      const startInput = document.getElementById('anim-start');
      if (startInput && !startInput.value) {{
        const d = new Date(minT), pad = n => String(n).padStart(2,'0');
        startInput.value = `${{d.getFullYear()}}-${{pad(d.getMonth()+1)}}-${{pad(d.getDate())}}T${{pad(d.getHours())}}:${{pad(d.getMinutes())}}`;
      }}

      renderSpeedPills();
      renderDurationPills();

      let hintText = animState.track.length + ' GPS points - ';
      hintText += animState.altFan.steps.length
        ? ('alternatives at ' + animState.altFan.steps.length + ' steps')
        : 'no alternatives loaded';
      hintText += animState.simTracks.length
        ? (' - ' + animState.simTracks.length + ' simulated realisations')
        : ' - no simulated paths';
      if (hint) hint.textContent = hintText;
      return true;
    }}

    function wireAnimationControls() {{
      document.getElementById('play-btn').addEventListener('click', () => animState.playing ? pauseAnimation() : playAnimation());
      document.getElementById('step-fwd').addEventListener('click', () => {{ pauseAnimation(); stepAnimation(1); }});
      document.getElementById('step-back').addEventListener('click', () => {{ pauseAnimation(); stepAnimation(-1); }});
      document.getElementById('reset-btn').addEventListener('click', () => {{
        pauseAnimation();
        if (animState.startTime != null) {{ animState.currentTime = animState.startTime; renderAnimationFrame(); }}
      }});

      const track = document.getElementById('track');
      track.addEventListener('pointerdown', e => {{
        scrubFromClientX(e.clientX);
        const move = ev => scrubFromClientX(ev.clientX);
        const up = () => {{ window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); }};
        window.addEventListener('pointermove', move);
        window.addEventListener('pointerup', up);
      }});

      const rangeToggle = document.getElementById('range-toggle');
      const rangePopover = document.getElementById('range-popover');
      rangeToggle.addEventListener('click', () => {{
        const open = rangePopover.style.display === 'block';
        rangePopover.style.display = open ? 'none' : 'block';
        rangeToggle.classList.toggle('open', !open);
      }});

      document.getElementById('anim-start').addEventListener('change', e => {{
        const t = parseTime(e.target.value);
        if (!isNaN(t)) applyRange(t, animState.durHours);
      }});
    }}

    map.on('load', () => {{
      addSourcesAndLayers();
      fitToData();
      wireMapControls();
      wireAnimationControls();
      initAnimation();
    }});
  </script>
</body>
</html>
"""
    components.html(html, height=height, scrolling=False)