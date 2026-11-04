"""
pages/3_Japan_Experiment.py
=============================
Japan experiment: one camera is selected, N simulated bears start there
at an actual photo event (place and time) and move according to the
Carpathian model (speed, optional terrain weighting, directional
persistence). Real photo times AT THAT CAMERA are marked as red ticks on
the same timeline, giving a direct visual comparison that requires no
statistical background to read: do simulated bears arrive at times
similar to the real sightings?

There is no "entire period" window as in the Carpathian animation: the
simulation has no natural end, only fixed windows from 15 minutes to
72 hours.

The Monte Carlo statistic (overlap coefficient with bootstrap confidence
interval over ALL cameras and runs, see activity_overlap.py) is kept but
moved into a collapsed section below. The animation answers the question
directly and without prior knowledge, so it comes first.
"""

import streamlit as st
import pandas as pd
from datetime import datetime

import activity_overlap as ao
import japan_map_component as jm
from japan_comparison import (
    load_japan_cameras, get_real_events_for_camera, simulate_multiple_bears_from_sighting,
    get_photo_counts_by_camera, DatabaseConnection, BearSpeeds, SIM_DB_PATH,
)
from wildlife_db_mariadb import WildlifeDatabase

st.set_page_config(page_title="Japan-Experiment", layout="wide")

st.title("Japan experiment: simulated bears versus real cameras")
st.caption(
    "Select a camera: several simulated bears start at an actual photo event "
    "(place and time) and move according to the Carpathian model. Red ticks on "
    "the timeline show when a photograph was actually taken at that camera."
)

# Introductory section shown above the map, aimed at readers who open
# the page without prior knowledge of the project.
with st.expander("What am I looking at?  ·  About this experiment", expanded=False):
    st.markdown("""
**The idea.** Movement patterns learned from GPS-collared brown bears in the
Romanian Carpathians are transferred to a camera-trap landscape in Japan
(Fukushima region, Honshu), where no collar data exists. The question is
whether simulated bears show up near cameras at times comparable to when real
photographs were actually triggered.

**Two very different kinds of data.** The Romanian data is tied to the
*animal*: a collar reports where one known bear is, hour by hour. The Japanese
data is tied to the *place*: a camera reports that some bear passed a fixed
point at a given moment, with no identity and no track. The two cannot be
compared directly — only through the timing and location of encounters.

**What the colours mean.**

| Element | Meaning |
|---|---|
| **Coloured** dots and trails | Simulated bears. All start from the same real photo event — same place, same timestamp — and then move independently. |
| **Grey** dots | Camera locations. Click one for its device ID, coordinates and number of real photographs. |
| **Yellow** flash | A camera lights up when a simulated bear comes within the detection radius. |
| **Red** ticks on the timeline | Times at which a photograph was actually taken at the selected camera. |

**What the animation shows.** Whether simulated bears approach cameras during
the same hours of the day in which real photographs cluster.

In this dataset the triggers are strongly nocturnal: 47 of 50 usable
timestamps (94%) fall between 18:00 and 06:00. That concentration is itself an
observation, not a given. Asian black bears are generally described in the
literature as cathemeral — active during both day and night — so a near-absence
of daytime triggers is something the data shows rather than something the
species dictates. One plausible reading is avoidance of humans: these cameras
are placed at human–wildlife conflict sites, where daytime activity carries a
cost for the animal. With 50 timestamps the pattern is indicative, not
established.

**What it does not show.** Each coloured path is **one random realisation** of
the model, not a prediction of where a bear went. Re-running with a different
seed produces different paths. A single run proves nothing; the quantitative
answer comes from the statistical comparison further down the page, which pools
many runs across all cameras into an overlap coefficient with a confidence
interval.

**Known limitations.** The Japanese cameras lie in the range of the Asian black
bear (*Ursus thibetanus*), while the model was trained on European brown bears
(*Ursus arctos*) — a deliberate simplification, not an equivalence. The number
of real photo timestamps is small, so results are indicative rather than
conclusive. Terrain weighting, when enabled, uses OpenStreetMap land-use data
with hand-set preferences, not coefficients fitted to observed habitat use.
""")


@st.cache_data(ttl=3600, show_spinner=False)
def _load_cameras_cached():
    return load_japan_cameras()


def _load_cameras():
    """
    Camera locations, cached for an hour.

    An empty result is NOT kept: it means the database was unreachable,
    and caching that would keep the page broken for an hour after the VPN
    is back. The cache entry is dropped so the next run tries again.
    """
    cameras = _load_cameras_cached()
    if not cameras:
        _load_cameras_cached.clear()
    return cameras


@st.cache_data(ttl=600, show_spinner=False)
def _check_db():
    return ao.check_db_reachable_bounded(WildlifeDatabase())


@st.cache_data(ttl=600, show_spinner=False)
def _get_real_events(device_id: str):
    """
    Real photo timestamps for one camera.

    Returns (events, error). The database call is wrapped because the
    reachability flag from _check_db() is cached for ten minutes: the VPN
    can drop within that window, in which case the flag still says
    "reachable" while the query already fails. Without this guard the
    exception propagates and takes the whole page down, even though the
    simulation itself does not need the database at all.
    """
    try:
        return get_real_events_for_camera(WildlifeDatabase(), device_id), ""
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"


@st.cache_data(ttl=600, show_spinner=False)
def _get_photo_counts():
    """
    Photo counts for all cameras, used by the clickable camera markers.
    One single query, cached (see get_photo_counts_by_camera).

    Returns None when the database cannot be reached, which the map
    renders as "unknown" rather than as "no photographs".
    """
    try:
        return get_photo_counts_by_camera(WildlifeDatabase())
    except Exception as e:
        print(f"[3_Japan_Experiment] Photo counts not retrievable: {e}")
        return None



@st.cache_data(ttl=3600, show_spinner=False)
def _comparison_cached(
    n_runs: int,
    seed: int,
    detection_radius_m: int,
) -> dict:
    """
    Berechnet die Statistik mit dem eingestellten
    Kameraradius und speichert das Ergebnis im Cache.
    """
    return ao.compute_comparison(
        n_runs=n_runs,
        hours_per_run=48,
        detection_radius_m=detection_radius_m,
        use_terrain=False,
        seed=seed,
    )



@st.cache_data(ttl=3600, show_spinner=False)
def _simulate(device_id: str, lat: float, lng: float, start_time_iso: str,
              n_bears: int, hours: int, use_terrain: bool, seed: int):
    """
    Returns:
        (bears, terrain_warning). terrain_warning is "" in the normal case, otherwise
        the reason why the run proceeded without terrain weighting.

    Terrain weighting is a convenience feature: if the cache cannot be
    opened, for example because terrain_cache.db is damaged or
    overwritten, the run continues WITHOUT weighting instead of letting
    the page crash. The reason is passed upwards and displayed there.
    """
    dbcon = DatabaseConnection(SIM_DB_PATH)
    bear_speeds = BearSpeeds(dbcon)
    terrain_cache = None
    terrain_warning = ""

    if use_terrain:
        try:
            from terrain_cache import TerrainCache
            terrain_cache = TerrainCache()
            if getattr(terrain_cache, "disabled", False):
                terrain_warning = terrain_cache.disabled_reason
                terrain_cache = None
        except Exception as e:
            terrain_warning = (
                f"Terrain cache could not be opened ({type(e).__name__}: {e}). "
                "The simulation runs without terrain weighting."
            )
            terrain_cache = None

    start_time = datetime.fromisoformat(start_time_iso)
    bears = simulate_multiple_bears_from_sighting(
        start_lat=lat, start_lng=lng, start_time=start_time,
        n_bears=n_bears, duration_hours=hours, bear_speeds=bear_speeds,
        seed=seed, terrain_cache=terrain_cache,
    )
    return bears, terrain_warning


DURATION_OPTIONS = [
    (0.25, "15 min"), (0.5, "30 min"), (1, "1 h"),
    (4, "4 h"), (24, "24 h"), (72, "72 h"),
]

cameras = _load_cameras()
db_ok = _check_db()

# ============================================================
# Sidebar
# ============================================================
with st.sidebar:
    st.header("Selection")

    if not db_ok:
        st.warning(
            "MariaDB not reachable (is the VPN active?). Both the camera "
            "locations and the real photo times come from the database, so "
            "this page needs the VPN. The Carpathian pages still work."
        )

    if not cameras:
        st.error(
            "No camera locations available. They are read from MariaDB "
            "(table deterrent_devices), which needs the university VPN. "
            "Start the VPN and reload the page."
        )
    else:
        cam_labels = {c["device_id"]: f"Kamera {c['device_id']}" for c in cameras}
        selected_cam_id = st.selectbox(
            "Kamera", options=list(cam_labels.keys()), format_func=lambda k: cam_labels[k],
        )
        selected_camera = next(c for c in cameras if c["device_id"] == selected_cam_id)

        real_events, events_error = _get_real_events(selected_cam_id) if db_ok else ([], "")
        if events_error:
            # Reachability flag was stale (see _get_real_events): report it
            # and continue without real events instead of failing the page.
            db_ok = False
            st.warning(
                "Database currently not reachable (is the VPN active?). The "
                "simulation continues, but no real photo times are shown. "
                f"Details: {events_error}"
            )
        elif db_ok:
            st.caption(f"{len(real_events)} real photograph(s) known at this camera.")

        with st.form("japan_exp_form"):
            if real_events:
                event_labels = [t.strftime("%d.%m.%Y %H:%M") for t in real_events]
                sel_event_idx = st.selectbox(
                    "Start time (actual photo event)",
                    options=range(len(real_events)), format_func=lambda i: event_labels[i],
                    index=len(real_events) - 1,
                    help="The bears start exactly at this real sighting, in place and time.",
                )
                start_time = real_events[sel_event_idx]
            else:
                st.info(
                    "No real photographs known at this camera, or no database "
                    "connection. The start time has to be chosen freely and no "
                    "comparison against reality is possible."
                )
                start_date = st.date_input("Start date", value=datetime(2024, 6, 1).date())
                start_hour = st.slider("Start hour", 0, 23, 20)
                start_time = datetime.combine(start_date, datetime.min.time()).replace(hour=start_hour)

            n_bears = st.slider("Number of simulated bears", 1, 20, 6)

            dur_label = st.select_slider(
                "Time window", options=[label for _, label in DURATION_OPTIONS], value="24 h",
                help="No 'entire period' option: the simulation has no natural end.",
            )
            hours = next(v for v, label in DURATION_OPTIONS if label == dur_label)

            detection_radius_m = st.slider("Camera detection radius (m)", 50, 300, 100, step=25)

            use_terrain = st.checkbox(
                "Terrain weighting (prefer forest)", value=False,
                help="Uses OpenStreetMap terrain data so that bears tend to move through "
                     "forest rather than villages. Requires internet access to Overpass "
                     "and can noticeably slow down the first run in a new area.",
            )
            seed = st.number_input("Random seed", min_value=0, max_value=999999, value=42)

            submitted = st.form_submit_button("Simulate", type="primary")

        if submitted:
            st.session_state["japan_exp2_radius_m"] = int(
                detection_radius_m
            )
            st.session_state["japan_exp2_params"] = (
                selected_cam_id, selected_camera["lat"], selected_camera["lng"],
                start_time.isoformat(), n_bears, int(hours), use_terrain, int(seed),
            )
            st.session_state["japan_exp2_real_events"] = real_events

    st.markdown("---")
    st.caption(
        "Red ticks on the timeline mark real photo times at the selected camera. "
        "Cameras on the map light up as soon as a simulated bear comes within range."
    )

# ============================================================
# Main area: animation
# ============================================================
if "japan_exp2_params" not in st.session_state:
    st.info("Select camera, start time and number of bears in the sidebar, then press **Simulate**.")
else:
    (cam_id, lat, lng, start_time_iso, n_bears, hours,
     use_terrain, seed) = st.session_state["japan_exp2_params"]

    real_events = st.session_state.get("japan_exp2_real_events", [])

    active_radius_m = st.session_state.get(
        "japan_exp2_radius_m", 100
    )

    start_camera = {"device_id": cam_id, "lat": lat, "lng": lng}

    with st.spinner(f"Simulating {n_bears} bears from camera {cam_id}..."):
        bears, terrain_warning = _simulate(
            cam_id, lat, lng, start_time_iso, n_bears, hours, use_terrain, seed
        )

    if terrain_warning:
        st.warning(terrain_warning)

    jm.render_japan_map(
        
        cameras=cameras, start_camera=start_camera, bears=bears,
        # None rather than {} when the database is unavailable; see
        # render_japan_map(). {} would mean "reachable, but zero
        # photographs everywhere".
        real_events=real_events, photo_counts=_get_photo_counts() if db_ok else None,
        detection_radius_m=active_radius_m,
        height=850,
    )

    st.markdown("### Data behind the current view")
    _tabs = st.tabs(["Camera locations", "Real photo times (start camera)", "Simulated bear paths"])

    with _tabs[0]:
        df_cam = pd.DataFrame(cameras)
        st.caption(f"{len(df_cam)} camera locations from MariaDB (deterrent_devices)")
        st.dataframe(df_cam, width="stretch")

    with _tabs[1]:
        if real_events:
            df_events = pd.DataFrame({"timestamp": real_events})
            st.caption(f"{len(df_events)} real photographs at camera {cam_id}")
            st.dataframe(df_events, width="stretch")
        else:
            st.info("No real photographs known, or no database connection.")

    with _tabs[2]:
        rows = []
        for b in bears:
            for p in b["path"]:
                rows.append({
                    "bear": f"Bear {b['bear_index'] + 1}", "sex": b["gender"],
                    "age": b["age"], "season": b["season"],
                    "time": p["time"], "lat": p["lat"], "lng": p["lng"],
                })
        df_bears = pd.DataFrame(rows)
        st.caption(f"{len(df_bears)} simulated positions across {len(bears)} bears")
        st.dataframe(df_bears, width="stretch")

    # ============================================================
    # Deeper analysis, collapsed and secondary (see module docstring)
    # ============================================================
    with st.expander("Deeper analysis: statistical comparison across all cameras"):
        st.caption(
            f"This analysis compares real photo times with simulated "
            f"camera entries across all 20 cameras. "
            f"Detection radius: {active_radius_m} m. "
            f"Each simulation run lasts 48 hours. "
            f"Terrain weighting is disabled for this comparison. "
            f"The selected camera and number of bears in the animation "
            f"do not affect this statistical analysis."
        )

        n_runs = st.slider(
            "Number of simulation runs (for the statistic)",
            50, 500, 300, step=50
        )

        with st.spinner(f"Computing the statistic over {n_runs} runs..."):
            stat_result = _comparison_cached(
                int(n_runs),
                int(seed),
                int(active_radius_m),
            )

        if not stat_result["db_ok"]:
            st.info("MariaDB not reachable; no statistical comparison possible.")
        elif stat_result["delta"] is None:
            st.warning("Not enough data for a statistical comparison.")
        else:
            col1, col2, col3 = st.columns(3)
            col1.metric("Overlap coefficient", f"{stat_result['delta']:.2f}")
            col2.metric("95 % confidence interval", f"[{stat_result['ci_low']:.2f}, {stat_result['ci_high']:.2f}]")
            col3.metric(
                "Real photos / virtual camera entries",
                f"{stat_result['n_real']} / {stat_result['n_sim']}"
            )

            st.caption(
                "The overlap coefficient runs from 0 to 1. It is the share of the "
                "daily rhythm that both sides have in common: 0 means the two are "
                "active at completely different hours, 1 means they are "
                "indistinguishable. The confidence interval gives the range in "
                "which the true value is expected to lie."
            )

            # Streamlit renders a matplotlib figure at 200 dpi, so these
            # two are about 1460 pixels wide. That is wider than the
            # content column, so they would be stretched across the whole
            # page and the reader would have to scroll past one figure to
            # reach the next. An explicit display width keeps them at a
            # readable size. Streamlit re-encodes the image at that
            # width, so the figure stays legible but is not available at
            # a higher resolution; for the report the figures are
            # generated separately as vector files.
            FIG_WIDTH_PX = 780
            st.markdown("#### 1. When are they active?")
            st.markdown(
                "Each curve shows how the detections of one side are distributed "
                "across the hours of the day, smoothed into a continuous line. "
                "**Blue** is the real camera photographs from Japan, **orange** "
                "the simulated bear driven by the Carpathian movement model. The "
                "grey area between them is the part both have in common, and its "
                "size is the overlap coefficient. Grey vertical bands mark the "
                "night. A high peak means many detections at that hour, not more "
                "animals."
            )
            fig1 = ao.build_activity_overlap_figure(
                stat_result["grid"], stat_result["f_real"], stat_result["f_sim"], stat_result["delta"],
                stat_result["ci_low"], stat_result["ci_high"], stat_result["n_real"], stat_result["n_sim"],
            )
            st.pyplot(fig1, clear_figure=True, width=FIG_WIDTH_PX)

            st.markdown("#### 2. How reliable is that number?")
            st.markdown(
                "The real sample is small, so the overlap coefficient would come "
                "out somewhat differently with a slightly different set of "
                "photographs. To estimate that, the sample is drawn again at "
                "random many times over and the coefficient recomputed each time. "
                "The histogram counts how often each value occurred. The **black "
                "line** is the value from the actual data, the **red dashed "
                "lines** enclose the middle 95 percent of the results. A narrow "
                "spread means the number is stable; a wide one means it should be "
                "read with care."
            )
            fig2 = ao.build_bootstrap_histogram_figure(
                stat_result["boot_deltas"], stat_result["delta"], stat_result["ci_low"], stat_result["ci_high"],
            )
            st.pyplot(fig2, clear_figure=True, width=FIG_WIDTH_PX)

            st.caption(
                "Both figures rest on a limited number of real photographs. They "
                "compare daily rhythms only, not positions, and the simulated "
                "side carries the behaviour of Carpathian brown bears rather than "
                "that of Asian black bears."
            )