"""
map.py
======
Main application: ONE shared map for all three subsystems.

Layout:
  - Sidebar, top: status widget for newly arrived images
  - Sidebar: filters per subsystem (Carpathian, Japan images, simulation)
  - Main area: ONE MapLibre map. Layers are SELECTED on the map itself
    (top left). On start the map is shown without data; ticking a layer
    makes it appear and the map zooms to it automatically.

Implementation note: the data of all subsystems is prepared in the
background (cached) and embedded into the map. The checkboxes on the map
only toggle visibility and zoom, so selection happens entirely in the
browser without reloading the page.
"""

import streamlit as st
from datetime import datetime

from status_widget import display_new_images_status, database_reachable
import maplibre_component as ml
from geojson_table_helper import geojson_to_dataframe

st.set_page_config(page_title="Wildlife Movement Analysis System", layout="wide")

# ============================================================
# Restore the map state from the URL, if present.
# maplibre_component.py writes centre, zoom, base map and visible layers
# on every interaction into the query parameters (window.parent.history.replaceState).
# On a rerun, for example after applying a filter, they are already in the
# URL and can be read back, so the map starts at the position last seen
# rather than at the default view.
# ============================================================
def _restore_map_state():
    qp = st.query_params

    def _qf(key):
        v = qp.get(key)
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    lat, lng, zoom = _qf("m_lat"), _qf("m_lng"), _qf("m_zoom")
    center = (lat, lng) if (lat is not None and lng is not None) else None

    basemap = qp.get("m_style") or ml.DEFAULT_BASEMAP
    if basemap not in ml.BASEMAP_NAMES:
        basemap = ml.DEFAULT_BASEMAP

    # Carry the 3D terrain toggle across reruns, like zoom and style
    terrain3d = qp.get("m_3d") == "1"

    layers_raw = qp.get("m_layers", "")
    # On the very first call no query parameter exists, so return None and
    # let render_maplibre() fall back to its default visibility logic.
    initial_visible = set(layers_raw.split(",")) if layers_raw else None

    return center, zoom, basemap, terrain3d, initial_visible


(_restored_center, _restored_zoom, _restored_basemap,
 _restored_terrain3d, _restored_visible) = _restore_map_state()

# Layers whose underlying data changed during this rerun
# (for example a different bear or period was selected). The map flies to
# them automatically, even if they were already visible; see the Carpathian
# and simulation blocks further down.
_refit_groups = set()


def _mark_refit_if_changed(session_key: str, new_signature, group_name: str):
    """Compare the current filter signature with the one from the previous
    rerun. On a change, group_name is added to _refit_groups so that the
    map navigates to the new data on the next load instead of staying at
    the old camera position restored from the URL."""
    old_signature = st.session_state.get(session_key)
    if old_signature != new_signature:
        _refit_groups.add(group_name)
    st.session_state[session_key] = new_signature

# ============================================================
# Sidebar: status widget and filters
# ============================================================
with st.sidebar:
    try:
        display_new_images_status(position="sidebar")
    except Exception as e:
        # The widget checks reachability itself and reports an unreachable
        # database as a plain note. Anything arriving here is a different
        # fault, so the technical detail stays available but behind an
        # expander rather than as a red error message.
        st.warning("Image status unavailable. Is the university VPN active?")
        with st.expander("Technical details"):
            st.caption(str(e))
    st.markdown("---")

st.sidebar.caption("Layers and base map style are selected on the map itself (top left).")
st.sidebar.markdown("---")

st.title("Wildlife Movement Analysis System")

# Data containers per subsystem, filled in advance
japan_data = None
carpathian_data = None
simulation_data = None


# ============================================================
# JAPAN  (always preloaded, lightweight)
#
# The reachability check runs first and shares its cached result with the
# status widget, so it costs no extra connection. Without it an
# unreachable database would stall this block for the full
# connection_timeout of 15 seconds, and because the page runs again on
# every interaction that delay would apply to every click.
# ============================================================
class _DatabaseUnreachable(Exception):
    """Raised instead of waiting for a connection that cannot succeed."""


try:
    if not database_reachable():
        raise _DatabaseUnreachable()

    from japan_deterrents import JapanDeterrentSystem

    @st.cache_resource
    def _get_japan_system():
        return JapanDeterrentSystem()

    # ------------------------------------------------------------
    # Handle new markers and areas that arrive as URL parameters from the
    # drawing tool on the map (maplibre_component.py, saveDrawing()).
    # This runs BEFORE the map data is loaded so that a new entry is
    # visible as soon as the page reloads after saving. The cache is
    # cleared explicitly; otherwise the previously cached
    # JapanDeterrentSystem instance would keep showing the state from
    # before the save.
    # ------------------------------------------------------------
    qp = st.query_params

    if "new_marker_lat" in qp and "new_marker_lng" in qp:
        try:
            lat = float(qp["new_marker_lat"])
            lng = float(qp["new_marker_lng"])
            from wildlife_db_mariadb import WildlifeDatabase
            db = WildlifeDatabase()
            new_id = db.get_next_marker_id()
            if db.save_marker(new_id, lat, lng):
                st.toast(f"Marker {new_id} saved.")
                _get_japan_system.clear()
            else:
                st.error("Marker could not be saved (check the database connection and VPN).")
        except Exception as e:
            st.error(f"Error while saving the marker: {e}")
        finally:
            del st.query_params["new_marker_lat"]
            del st.query_params["new_marker_lng"]
            st.rerun()

    if "new_polygon_coords" in qp and "new_polygon_name" in qp:
        try:
            import json as _json
            coords = _json.loads(qp["new_polygon_coords"])
            name = qp["new_polygon_name"]
            from wildlife_db_mariadb import WildlifeDatabase
            db = WildlifeDatabase()
            new_id = db.get_next_polygon_id()
            polygon_id = f"poly-{new_id}"
            if db.save_polygon(polygon_id, name, coords):
                st.toast(f"Area \"{name}\" saved.")
                _get_japan_system.clear()
            else:
                st.error("Area could not be saved (check the database connection and VPN).")
        except Exception as e:
            st.error(f"Error while saving the area: {e}")
        finally:
            del st.query_params["new_polygon_coords"]
            del st.query_params["new_polygon_name"]
            st.rerun()

    jp = _get_japan_system()
    japan_data = {
        "deterrents": jp._df_to_geojson_points(jp.deterrent_data, kind="deterrent"),
        "markers": jp._df_to_geojson_points(jp.existing_markers, kind="marker"),
        "polygons": jp._polygons_to_geojson(jp.existing_polygons),
    }

    # Japan image and device browser (the class brings its own sidebar UI)
    jp.display_device_images_in_sidebar()
    st.sidebar.markdown("---")

except Exception as e:
    # Same reasoning as for the status widget above: the Japan data lives
    # in the MariaDB instance, which is only reachable through the
    # university VPN. That is the common case, so it is named first. A
    # fault of any other kind still shows its message, one click away.
    st.warning(
        "Japan data unavailable. Is the university VPN active? "
        "All other layers remain usable."
    )
    if not isinstance(e, _DatabaseUnreachable):
        with st.expander("Technical details"):
            st.caption(str(e))


# ============================================================
# CARPATHIAN (filters inside a form, so data reloads only on "Apply")
# ============================================================
try:
    from carpathian_bears import (get_carpathian_geojson, get_carpathian_options,
                                   SEASON_HELP)

    bears, seasons, min_date, max_date = get_carpathian_options()

    with st.sidebar.expander("Carpathian: Filter", expanded=False):
        if not bears:
            st.info("No Carpathian data found.")
            sel_bears, sel_seasons = [], []
            sd, ed = min_date, max_date
            map_type, max_pts = "Movement Paths", 3000
        else:
            with st.form("cp_form"):
                select_all = st.checkbox("All bears", value=False)
                bears_choice = st.multiselect(
                    "Bears", bears, default=bears[: min(2, len(bears))]
                )
                sel_seasons = st.multiselect(
                    "Season", seasons, default=seasons, help=SEASON_HELP,
                )
                st.caption(
                    "Biological annual phases of the bear, not calendar seasons. "
                    "See the (?) next to the field."
                )
                date_range = st.date_input(
                    "Period", value=(min_date, max_date),
                    min_value=min_date, max_value=max_date,
                )
                map_type = st.selectbox("Display", ["Movement Paths", "Daily Positions"], index=0)
                max_pts = st.slider("Max. points per bear", 300, 20000, 3000, 100)
                st.form_submit_button("Apply", type="primary")

            sel_bears = bears if select_all else bears_choice
            if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
                sd, ed = date_range
            else:
                sd, ed = min_date, max_date

    start_dt = datetime.combine(sd, datetime.min.time())
    end_dt = datetime.combine(ed, datetime.max.time())

    if sel_bears:
        with st.spinner("Preparing Carpathian data..."):
            carpathian_data = get_carpathian_geojson(
                selected_bears=sel_bears,
                start_datetime=start_dt,
                end_datetime=end_dt,
                selected_seasons=sel_seasons,
                map_type=map_type,
                max_points_per_bear=max_pts,
            )
        _mark_refit_if_changed(
            "cp_filter_sig",
            (tuple(sorted(sel_bears)), tuple(sorted(sel_seasons)), str(sd), str(ed), map_type, max_pts),
            "carpathian",
        )

except Exception as e:
    st.error(f"Error while loading the Carpathian data: {e}")


# ============================================================
# SIMULATION (movement model of Fabian Breu, fully integrated)
# Always preloaded with defaults (first bear, 10 alternatives) so that the
# checkbox on the map is available from the start.
# ============================================================
try:
    from bear_simulation import get_simulation_geojson, get_simulation_options, SEASON_ORDER

    sim_bear_ids, sim_seasons_info = get_simulation_options()

    with st.sidebar.expander("Bear Simulation: Filter", expanded=False):
        if not sim_bear_ids:
            st.warning(
                "bear_simulation/data/database.db not found. "
                "Copy the contents of bearsimulation-master into bear_simulation/."
            )
            _sim_bear   = None
            _sim_season = None
            _sim_num_alt = 10
        else:
            # Which bear is currently committed, that is, applied last?
            _committed_bear = st.session_state.get(
                "sim_committed_bear", str(sim_bear_ids[0])
            )
            # Seasons available for the committed bear, before submitting
            _avail_seasons = sim_seasons_info.get(_committed_bear, {})
            # Sorted by the defined order, unknown values last
            _sorted_seasons = sorted(
                _avail_seasons.keys(),
                key=lambda s: SEASON_ORDER.index(s) if s in SEASON_ORDER else 99,
            )
            # Readable labels: "Autumn", "Summer", ...
            _season_labels = [s.capitalize() for s in _sorted_seasons]

            with st.form("sim_form"):
                _sim_bear = st.selectbox(
                    "Select bear",
                    sim_bear_ids,
                    index=sim_bear_ids.index(_committed_bear)
                          if _committed_bear in sim_bear_ids else 0,
                    key="sim_bear_sel",
                    help="Only bears with at least 5 GPS steps are listed",
                )
                if _season_labels:
                    _sim_season_label = st.selectbox(
                        "Season",
                        _season_labels,
                        help="Each option reflects the exact number of real GPS "
                             "steps for this bear in this season",
                    )
                    # Derive the season key from the label ("Autumn" -> "autumn")
                    _sim_season = _sim_season_label.lower()
                else:
                    st.info("No season data available for this bear.")
                    _sim_season_label = None
                    _sim_season = None

                _sim_num_alt = st.slider(
                    "Alternatives per step",
                    min_value=3, max_value=20, value=10,
                    help="Number of simulated alternative positions per real GPS step",
                )
                submitted = st.form_submit_button("Apply", type="primary")
                if submitted:
                    st.session_state["sim_committed_bear"] = str(_sim_bear)

    # Always load so the simulation checkbox on the map works immediately
    if sim_bear_ids and _sim_bear is not None and _sim_season is not None:
        with st.spinner("Loading simulation data..."):
            simulation_data = get_simulation_geojson(
                bear_id=str(_sim_bear),
                season=_sim_season,
                num_alternatives=_sim_num_alt,
            )
        _mark_refit_if_changed(
            "sim_filter_sig",
            (str(_sim_bear), _sim_season, _sim_num_alt),
            "simulation",
        )
        # Status caption
        feats  = simulation_data.get("points", {}).get("features", [])
        n_real = sum(1 for f in feats if f["properties"].get("type") == "real")
        n_alt  = sum(1 for f in feats if f["properties"].get("type") == "alternative")
        if n_alt > 0:
            _season_disp = _sim_season.capitalize()
            _total = n_real + n_alt
            st.sidebar.caption(
                f"Bear {_sim_bear} / {_season_disp}: "
                f"{n_real} real steps x {_sim_num_alt} alternatives "
                f"= {_total} points in total"
            )
        else:
            st.sidebar.caption(
                f"Bear {_sim_bear}: {n_real} GPS points (fallback mode)"
            )

except ImportError:
    pass
except Exception as e:
    st.error(f"Error while loading the simulation: {e}")


# ============================================================
# WOLF/LYNX (BfN) and BEAR SIGHTINGS (GBIF): external, public APIs.
# No VPN required, unlike the MariaDB subsystems, but behind its own
# checkbox in the sidebar for offline work or to avoid the requests.
# ============================================================
wolf_lynx_data = None
gbif_bears_data = None

with st.sidebar.expander("External reference data", expanded=False):
    load_external = st.checkbox(
        "Load wolf/lynx (BfN) and bear sightings (GBIF)",
        value=True,
        help="Free, public data sources. Wolf and lynx records from the "
             "German Federal Agency for Nature Conservation, bear sightings "
             "from GBIF (Germany and Romania).",
    )

if load_external:
    try:
        from import_bfn_wolf_lynx import get_wolf_lynx_geojson
        wolf_lynx_data = get_wolf_lynx_geojson()
    except Exception as e:
        st.sidebar.warning(f"Wolf and lynx data (BfN) unavailable: {e}")

    try:
        from import_gbif_bears import get_gbif_bears_geojson
        gbif_bears_data = get_gbif_bears_geojson()
    except Exception as e:
        st.sidebar.warning(f"Bear sightings (GBIF) unavailable: {e}")


# ============================================================
# Render the map (empty on start; selection and zoom happen on the map)
# ============================================================
ml.render_maplibre(
    japan=japan_data,
    carpathian=carpathian_data,
    simulation=simulation_data,
    wolf_lynx=wolf_lynx_data,
    gbif_bears=gbif_bears_data,
    basemap=_restored_basemap,        # last chosen style, otherwise satellite
    terrain3d=_restored_terrain3d,    # carry over the 3D toggle state
    center=_restored_center,          # last camera position, otherwise default
    zoom=_restored_zoom,
    initial_visible=_restored_visible,  # last visible layers, otherwise defaults
    refit_on_load=_refit_groups,      # layers with changed filters: fly to them
    height=800,
)

st.caption(
    "Tick the layers at the top left of the map. Ticking a layer makes the "
    "map zoom to its data automatically. Which bears and filters are loaded "
    "is configured in the sidebar."
)

# ============================================================
# Data tables below the map, built from the same variables that feed the
# map rather than from a second query, so the rendered map can be checked
# against its underlying data.
# ============================================================
st.markdown("### Data behind the current map view")

_table_tabs = st.tabs([
    "Japan devices", "Japan markers and areas", "Carpathian GPS",
    "Simulation", "Wolf and lynx", "GBIF bear sightings",
])

with _table_tabs[0]:
    df = geojson_to_dataframe((japan_data or {}).get("deterrents"))
    st.caption(f"{len(df)} deterrent devices" if not df.empty else "No data loaded.")
    if not df.empty:
        st.dataframe(df, width="stretch")

with _table_tabs[1]:
    df_m = geojson_to_dataframe((japan_data or {}).get("markers"))
    df_p = geojson_to_dataframe((japan_data or {}).get("polygons"))
    st.caption(f"{len(df_m)} markers, {len(df_p)} areas")

    if not df_m.empty:
        st.markdown("**Markers**")
        st.dataframe(df_m, width="stretch")
        with st.expander("Delete marker"):
            del_marker_id = st.selectbox("Marker to delete", df_m["id"], key="del_marker_sel")
            confirm_marker = st.checkbox("Yes, delete it", key="confirm_del_marker")
            if st.button("Delete marker", disabled=not confirm_marker, key="btn_del_marker"):
                from wildlife_db_mariadb import WildlifeDatabase
                if WildlifeDatabase().delete_marker(del_marker_id):
                    st.toast(f"Marker {del_marker_id} deleted.")
                    _get_japan_system.clear()
                    st.rerun()
                else:
                    st.error("Deletion failed (check the database connection and VPN).")

    if not df_p.empty:
        st.markdown("**Areas**")
        st.dataframe(df_p, width="stretch")
        with st.expander("Delete area"):
            _poly_labels = {row["polygon_id"]: f"{row.get('name', '')} ({row['polygon_id']})" for _, row in df_p.iterrows()}
            del_poly_id = st.selectbox(
                "Area to delete", options=list(_poly_labels.keys()),
                format_func=lambda k: _poly_labels[k], key="del_poly_sel",
            )
            confirm_poly = st.checkbox("Yes, delete it", key="confirm_del_poly")
            if st.button("Delete area", disabled=not confirm_poly, key="btn_del_poly"):
                from wildlife_db_mariadb import WildlifeDatabase
                if WildlifeDatabase().delete_polygon(del_poly_id):
                    st.toast(f"Area {del_poly_id} deleted.")
                    _get_japan_system.clear()
                    st.rerun()
                else:
                    st.error("Deletion failed (check the database connection and VPN).")

    if df_m.empty and df_p.empty:
        st.info("No markers or areas in the database.")

with _table_tabs[2]:
    df = geojson_to_dataframe((carpathian_data or {}).get("points"))
    st.caption(f"{len(df)} GPS points in the selected period and filters" if not df.empty else "No data loaded.")
    if not df.empty:
        st.dataframe(df, width="stretch")

with _table_tabs[3]:
    df = geojson_to_dataframe((simulation_data or {}).get("points"))
    st.caption(f"{len(df)} simulated points (real plus alternatives)" if not df.empty else "No data loaded.")
    if not df.empty:
        st.dataframe(df, width="stretch")

with _table_tabs[4]:
    df = geojson_to_dataframe(wolf_lynx_data)
    st.caption(f"{len(df)} grid cells (wolf and lynx)" if not df.empty else "No data loaded (is \"External reference data\" enabled?).")
    if not df.empty:
        st.dataframe(df, width="stretch")

with _table_tabs[5]:
    df = geojson_to_dataframe(gbif_bears_data)
    st.caption(f"{len(df)} bear sightings (DE and RO)" if not df.empty else "No data loaded (is \"External reference data\" enabled?).")
    if not df.empty:
        st.dataframe(df, width="stretch")

# ============================================================
# Footer
# ============================================================
st.markdown(
    """
---
### About this application

An integrated system covering:
1. **Japan bear deterrent system** - deterrent devices and camera images in Japan
2. **Carpathian bear movement** - movement patterns of brown bears in the Carpathians
3. **Bear movement simulation** - model-based simulation of bear movement

Built for wildlife research and management.
"""
)