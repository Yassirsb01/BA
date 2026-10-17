"""Apply a small Streamlit 1.55 marker/polygon save bridge without changing the map architecture.

Run once in the bears/streamlit_app directory:
    python <path-to>/apply_marker_save_fix.py

This script only updates map.py and maplibre_component.py, keeps backups,
checks expected source fragments, and validates Python syntax before writing.
"""
from __future__ import annotations

import ast
from pathlib import Path
import shutil
import sys


ROOT = Path.cwd()
MAP = ROOT / "map.py"
MAPLIBRE = ROOT / "maplibre_component.py"


def replace_one(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected one matching source fragment, found {count}. No files were changed.")
    return source.replace(old, new, 1)


DRAWING_SAVE_BRIDGE = r'''<script>
(() => {
  // Executed in the main Streamlit document, not inside the MapLibre iframe.
  // It receives a message from the existing static components.html() map.
  const token = __SAVE_TOKEN__;
  const previous = window.__wildlifeDrawingSaveHandler;
  if (previous) window.removeEventListener('message', previous);

  function validCoordinate(lng, lat) {
    return Number.isFinite(lng) && Number.isFinite(lat)
      && Math.abs(lng) <= 180 && Math.abs(lat) <= 90;
  }

  function onDrawingSave(event) {
    const msg = event.data;
    if (!msg || typeof msg !== 'object'
        || msg.type !== 'wildlife-drawing-save' || msg.token !== token) return;

    const url = new URL(window.location.href);
    if (msg.kind === 'marker') {
      const lat = Number(msg.lat);
      const lng = Number(msg.lng);
      if (!validCoordinate(lng, lat)) return;
      url.searchParams.set('new_marker_lat', lat.toFixed(6));
      url.searchParams.set('new_marker_lng', lng.toFixed(6));
      url.searchParams.delete('new_polygon_name');
      url.searchParams.delete('new_polygon_coords');
    } else if (msg.kind === 'polygon') {
      const pts = msg.coords;
      const name = typeof msg.name === 'string' ? msg.name.trim() : '';
      if (!name || name.length > 128 || !Array.isArray(pts)
          || pts.length < 3 || pts.length > 500
          || !pts.every(p => Array.isArray(p) && p.length === 2
            && validCoordinate(Number(p[0]), Number(p[1])))) return;
      url.searchParams.set('new_polygon_name', name);
      url.searchParams.set('new_polygon_coords', JSON.stringify(pts));
      url.searchParams.delete('new_marker_lat');
      url.searchParams.delete('new_marker_lng');
    } else {
      return;
    }

    // Acknowledge that the request reached the main document.
    // Do not confuse this with a successful MariaDB write.
    if (event.source) {
      event.source.postMessage({type: 'wildlife-drawing-accepted', token}, '*');
    }
    // Navigation from the main page works without iframe top-navigation rights.
    // Existing st.query_params code persists the drawing in MariaDB.
    window.location.assign(url.toString());
  }

  window.__wildlifeDrawingSaveHandler = onDrawingSave;
  window.addEventListener('message', onDrawingSave);
})();
</script>'''


def prepare_map(src: str) -> str:
    src = replace_one(
        src,
        "import streamlit as st\nfrom datetime import datetime\n",
        "import streamlit as st\nimport json\nimport secrets\nfrom datetime import datetime\n",
        "map.py imports",
    )
    marker = "# Render the map (empty on start; selection and zoom happen on the map)\n# ============================================================\nml.render_maplibre("
    replacement = (
        "# Render the map (empty on start; selection and zoom happen on the map)\n"
        "# ============================================================\n"
        "# One-way browser message bridge for saving map drawings. This is not a\n"
        "# bidirectional Streamlit component. The existing map remains in\n"
        "# components.html(); Python still receives drawings via query parameters.\n"
        "if \"drawing_save_token\" not in st.session_state:\n"
        "    st.session_state[\"drawing_save_token\"] = secrets.token_urlsafe(24)\n"
        "st.html(\n"
        "    _DRAWING_SAVE_BRIDGE.replace(\n"
        "        \"__SAVE_TOKEN__\", json.dumps(st.session_state[\"drawing_save_token\"])\n"
        "    ),\n"
        "    unsafe_allow_javascript=True,\n"
        ")\n\n"
        "ml.render_maplibre("
    )
    src = replace_one(src, marker, replacement, "map.py bridge insertion")
    src = replace_one(
        src,
        "    refit_on_load=_refit_groups,      # layers with changed filters: fly to them\n    height=800,",
        "    refit_on_load=_refit_groups,      # layers with changed filters: fly to them\n"
        "    save_token=st.session_state[\"drawing_save_token\"],\n    height=800,",
        "map.py save token parameter",
    )
    # Add the script as a standalone literal before the first streamlit operation.
    src = replace_one(
        src,
        'st.set_page_config(page_title="Wildlife Movement Analysis System", layout="wide")',
        '_DRAWING_SAVE_BRIDGE = r"""' + DRAWING_SAVE_BRIDGE + '"""\n\n'
        'st.set_page_config(page_title="Wildlife Movement Analysis System", layout="wide")',
        "map.py script constant",
    )
    return src


def prepare_maplibre(src: str) -> str:
    src = replace_one(
        src,
        "    refit_on_load: set = None,\n    height: int = 650,\n",
        "    refit_on_load: set = None,\n    height: int = 650,\n    save_token: str = \"\",\n",
        "maplibre_component.py signature",
    )
    src = replace_one(
        src,
        "    refit_json = json.dumps(sorted(refit_on_load)) if refit_on_load else \"[]\"\n",
        "    refit_json = json.dumps(sorted(refit_on_load)) if refit_on_load else \"[]\"\n"
        "    save_token_json = json.dumps(save_token)\n",
        "maplibre_component.py token serialization",
    )
    src = replace_one(
        src,
        "    const STYLES = {styles_js};\n",
        "    const STYLES = {styles_js};\n    const SAVE_TOKEN = {save_token_json};\n",
        "maplibre_component.py JS token",
    )
    old = '''    function saveDrawing() {{
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
    }}'''
    new = '''    // Static components.html iframe: cannot read or navigate the parent URL.
    // Send just the drawing; a trusted main-page st.html script updates the URL.
    let drawingSavePending = false;
    window.addEventListener('message', e => {{
      if (e.source !== window.parent || !e.data ||
          e.data.type !== 'wildlife-drawing-accepted' || e.data.token !== SAVE_TOKEN) return;
      drawingSavePending = false;
      setDrawHint('Saving in database...');
    }});

    function saveDrawing() {{
      if (drawingSavePending) return;
      const msg = {{ type: 'wildlife-drawing-save', token: SAVE_TOKEN }};
      if (drawState.mode === 'marker' && drawState.pendingMarker) {{
        msg.kind = 'marker';
        msg.lat = drawState.pendingMarker.lat;
        msg.lng = drawState.pendingMarker.lng;
      }} else if (drawState.mode === 'polygon' && drawState.polygonPoints.length >= 3) {{
        const nameInput = document.getElementById('draw-name-input');
        msg.kind = 'polygon';
        msg.name = nameInput.value.trim();
        msg.coords = drawState.polygonPoints;
      }} else {{
        return;
      }}
      if (!SAVE_TOKEN) {{
        setDrawHint('Save unavailable. Reload the application.');
        return;
      }}
      drawingSavePending = true;
      setDrawHint('Sending drawing to Streamlit...');
      document.getElementById('draw-save-btn').disabled = true;
      window.parent.postMessage(msg, '*');
      window.setTimeout(() => {{
        if (!drawingSavePending) return;
        drawingSavePending = false;
        setDrawHint('No response from the main page. Reload and try again.');
        updateSaveButtonState();
      }}, 5000);
    }}'''
    src = replace_one(src, old, new, "maplibre_component.py drawing save handler")
    return src


def main() -> None:
    if not MAP.is_file() or not MAPLIBRE.is_file():
        raise FileNotFoundError("Run the script inside bears/streamlit_app (map.py and maplibre_component.py must exist).")
    originals = {MAP: MAP.read_text(encoding="utf-8"), MAPLIBRE: MAPLIBRE.read_text(encoding="utf-8")}
    if "wildlife-drawing-save" in originals[MAPLIBRE]:
        print("The drawing-save bridge appears to be already installed. No changes made.")
        return
    updated = {MAP: prepare_map(originals[MAP]), MAPLIBRE: prepare_maplibre(originals[MAPLIBRE])}
    for path, text in updated.items():
        ast.parse(text, filename=str(path))
    backups = {}
    for path in updated:
        backup = path.with_name(path.name + ".before_marker_save_fix.bak")
        if backup.exists():
            raise FileExistsError(f"Backup already exists: {backup}. No changes made.")
        backups[path] = backup
    # Backups first; only write if both files pass all checks.
    for path, backup in backups.items():
        shutil.copy2(path, backup)
    written = []
    try:
        for path, text in updated.items():
            path.write_text(text, encoding="utf-8", newline="\n")
            written.append(path)
    except Exception:
        for path in written:
            shutil.copy2(backups[path], path)
        raise
    print("Marker/polygon save bridge installed successfully.")
    print("Updated: map.py, maplibre_component.py")
    print("Backups:")
    for backup in backups.values():
        print(" ", backup.name)
    print("Next: python -m py_compile map.py maplibre_component.py")
    print("Then restart Streamlit and test saving ONE marker and ONE area.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("No partial update should remain. Error:", exc, file=sys.stderr)
        sys.exit(1)
