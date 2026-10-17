"""
pages/2_Experiments.py
========================
Analysis page: movement animation of the Carpathian bears. The real GPS
route and several simulated bears advance along the same time axis (see
sync_simulation.py); the fan of candidate steps can be shown in addition.

Why SEVERAL simulated bears instead of one: each path is only one random
draw from the model. A single path next to the real route would be read
as "the model predicts this route", whereas several diverging paths show
the space of possibilities directly. The seed makes every run exactly
reproducible, which matters for figures.

The page is aimed at readers who want to follow how a particular bear
moved through the terrain on a particular day, and how plausible the
simulated alternatives are. Therefore:
  - filters for bear, season and day (only days WITH data are selectable)
  - the data source is shown explicitly (MariaDB or CSV fallback)
  - satellite imagery and optional 3D terrain for spatial context

Performance principle: only ONE day is loaded server-side, but at full
resolution without downsampling, rather than the complete multi-year
history.
"""

import streamlit as st
from datetime import datetime, timedelta

import animation_component as anim
import sync_simulation as sync
from geojson_table_helper import geojson_to_dataframe

st.set_page_config(page_title="Bewegungs-Animation", layout="wide")


def _deduplicate_gps_points(carpathian_data: dict) -> dict:
    """Remove repeated fixes only for the animation, without modifying source data.

    Equal bear ID, timestamp and coordinates represent the same GPS fix.
    Distinct positions at the same timestamp are deliberately left untouched.
    """
    points = carpathian_data.get("points", {})
    features = points.get("features", [])
    seen = set()
    unique_features = []
    for feature in features:
        props = feature.get("properties", {})
        coords = tuple(feature.get("geometry", {}).get("coordinates", []))
        key = (props.get("bear_id"), props.get("timestamp"), coords)
        if key in seen:
            continue
        seen.add(key)
        unique_features.append(feature)

    if len(unique_features) == len(features):
        return carpathian_data
    return {
        **carpathian_data,
        "points": {**points, "features": unique_features},
    }


# ============================================================
# Determine the data source, for display on the map
# ============================================================
@st.cache_data(ttl=300, show_spinner=False)
def _get_data_source_label() -> str:
    """
    Check once, cached, whether MariaDB is reachable. This matters for
    traceability: it has to be visible whether the data comes live from
    the project database or from the local CSV fallback.
    """
    try:
        from wildlife_db_mariadb import WildlifeDatabase
        db = WildlifeDatabase()
        conn = db._get_connection()
        conn.close()
        host = db.db_config.get("host", "?")
        database = db.db_config.get("database", "?")
        return f"MariaDB · {database}@{host}"
    except Exception:
        return "Local CSV fallback (no database connection)"


@st.cache_data(show_spinner=False)
def _load_and_simulate(bear: str, date_str: str, seasons_key: tuple,
                       num_alt: int, n_real: int, seed: int) -> dict:
    """
    Load ONE day and compute the matching simulation, cached.

    Why this is cached: Streamlit re-executes the whole script on EVERY
    interaction. Without a cache, build_synced_geojson() ran again each
    time, the generated HTML of the map component changed, the iframe was
    rebuilt and the animation restarted from the beginning. With the
    cache, a rerun with unchanged parameters returns exactly the same
    result and the iframe stays in place.

    All inputs are scalar: the day is loaded INSIDE the function instead
    of passing the GeoJSON in as an argument. Otherwise st.cache_data
    would have to hash a dict with thousands of features on every rerun.

    seasons_key is a tuple, and therefore hashable, and deliberately part
    of the cache key: the season selection determines which points the
    day contains in the first place.
    """
    from carpathian_bears import get_carpathian_geojson

    day = datetime.strptime(date_str, "%Y-%m-%d").date()
    start_dt = datetime.combine(day, datetime.min.time())
    end_dt = start_dt + timedelta(days=1)

    carpathian_data = get_carpathian_geojson(
        selected_bears=[bear],
        start_datetime=start_dt,
        end_datetime=end_dt,
        selected_seasons=list(seasons_key),
        map_type="Movement Paths",
        max_points_per_bear=50000,  # one day, so no reduction is needed
    )
    carpathian_data = _deduplicate_gps_points(carpathian_data)

    synced = sync.build_synced_geojson(
        carpathian_data.get("points", {}),
        num_alternatives=num_alt,
        n_realizations=n_real,
        seed=seed,
    )
    return {
        "carpathian": carpathian_data,
        "alternative": synced["alternative"],
        "simulated": synced["simulated"],
        "warnings": synced["warnings"],
    }


def _run_id(sim_geojson: dict) -> str:
    """
    Short identifier of the simulated paths, a hash over all coordinates.

    Useful for debugging and for traceability: if the identifier stays the
    same across a rerun, the simulation is unchanged and the animation was
    merely restarted. If it changes, the data really did change. It also
    makes it possible to match a screenshot to a specific run later.
    """
    import hashlib
    coords = "".join(
        f"{f['geometry']['coordinates'][0]:.6f},{f['geometry']['coordinates'][1]:.6f};"
        for f in (sim_geojson or {}).get("features", [])
    )
    return hashlib.sha1(coords.encode()).hexdigest()[:8] if coords else "–"


st.title("Movement animation: real versus simulated")
st.caption(
    "One bear, one day: the real GPS movement (blue) and several simulated "
    "bears (orange) advance along the same time axis. The fan of candidate "
    "steps (grey) can be shown in addition. "
    "Dataset: Carpathian Bears, GPS tracking in Romania."
)

# Introductory section shown above the map, aimed at readers who open the
# page without prior knowledge of the project.
with st.expander("What am I looking at?  ·  About this experiment", expanded=False):
    st.markdown("""
**The dataset.** GPS collar data from brown bears (*Ursus arctos*) in the
Romanian Carpathians: 13 individuals and 59,997 fixes, recorded from
9 August 2011 to 31 July 2015. Fix intervals are about one hour — 80% fall
between 0.9 and 1.1 hours, 13% around two hours, the rest longer. One bear on
one day is loaded at a time, at full resolution.

**What the colours mean.**

| Colour | Meaning |
|---|---|
| **Blue** dot and trail | The bear's actual recorded GPS track, interpolated between fixes. |
| **Orange** dots and trails | Simulated bears, generated by the movement model. Several are shown at once; each is a separate run. |
| **Grey** fan (optional) | At every real step, all candidate moves the model considered at that moment. |

**What the animation shows.** Real and simulated bears advance along the
*same* timeline, starting from the *same* position. Both are driven by the
timestamps of the real GPS track, so any separation you see between them
accumulated within that time window. The "Abstand ø" readout gives the current
mean distance between the real bear and the simulated ones.

**What it does not show.** The orange paths are **not predictions** and not a
reconstruction of anything the bear actually did. Each is one random
realisation drawn from the model: change the seed and you get different paths
from the same starting point. This is why several are drawn at once — the
spread between them is the meaningful part, not any single line. A simulated
bear ending up far from the real one is not in itself a modelling failure.

**The question behind it.** Given step lengths and turning behaviour learned
from real bears, does the model produce movement that is *plausible* for this
landscape and this time of year? The comparison is distributional — how far
bears travel, how tortuous their paths are — not a point-by-point match.

**Reproducibility.** Every run is identified by the short hash shown above the
map. The same bear, day, season selection, seed and settings always reproduce
exactly the same paths.
""")

carpathian_data = None
alt_geojson = None
sim_geojson = None
sync_warnings = []
selected_bear_label = ""

source_label = _get_data_source_label()

# ============================================================
# Sidebar: bear, then season, then day (only days WITH data)
# ============================================================
with st.sidebar:
    st.header("Selection")
    st.caption(f"Data source: {source_label}")

    try:
        from carpathian_bears import (get_carpathian_geojson, get_carpathian_options,
                                       SEASON_HELP)

        bears, seasons, min_date, max_date = get_carpathian_options()

        if not bears:
            st.info("No Carpathian data found.")
        else:
            sel_bear = st.selectbox("Bear", bears, key="anim_bear")

            sel_seasons = st.multiselect(
                "Season", seasons, default=seasons,
                help="Restricts the selectable days to the chosen phases.\n\n"
                     + SEASON_HELP,
            )
            st.caption(
                "Biological annual phases of the bear, not calendar seasons. "
                "See the (?) for details."
            )
            if not sel_seasons:
                sel_seasons = seasons  # an empty selection means no restriction

            # Which days does this bear have data for in these seasons?
            # Cached so the query does not run on every interaction.
            @st.cache_data(ttl=3600, show_spinner=False)
            def _get_available_dates(bear, seasons_tuple, min_d, max_d):
                fc = get_carpathian_geojson(
                    selected_bears=[bear],
                    start_datetime=datetime.combine(min_d, datetime.min.time()),
                    end_datetime=datetime.combine(max_d, datetime.max.time()),
                    selected_seasons=list(seasons_tuple),
                    map_type="Movement Paths",
                    max_points_per_bear=200000,
                )
                dates = set()
                for f in fc.get("points", {}).get("features", []):
                    ts = f.get("properties", {}).get("timestamp")
                    if ts:
                        dates.add(str(ts)[:10])
                return sorted(dates)

            with st.spinner(f"Checking available days for {sel_bear}..."):
                available_dates = _get_available_dates(
                    sel_bear, tuple(sorted(sel_seasons)), min_date, max_date
                )

            if not available_dates:
                st.warning(
                    f"No GPS data for {sel_bear} in the selected seasons. "
                    "Choose a different season or a different bear."
                )
            else:
                with st.form("anim_form"):
                    sel_date_str = st.selectbox(
                        "Day", available_dates,
                        help=f"{len(available_dates)} days with real GPS data.",
                    )
                    num_alt = st.slider(
                        "Alternatives per step", 3, 20, 10,
                        help="How many candidate headings the model generates per "
                             "real GPS step (the fan on the map).",
                    )
                    n_real = st.slider(
                        "Simulated bears (realisations)", 0, 8, 3,
                        help="Each simulated bear is ONE possible model run, not a "
                             "prediction. Several runs show how far the model can "
                             "spread from an identical start. 0 hides them.",
                    )
                    anim_seed = st.number_input(
                        "Random seed", min_value=0, max_value=999999, value=42,
                        help="The same seed reproduces exactly the same run. Changing "
                             "the seed draws new realisations, which shows that a "
                             "single path proves nothing.",
                    )
                    submitted = st.form_submit_button("Load", type="primary")

                if submitted:
                    # sel_seasons belongs in the parameters. It used to be
                    # read live from the multiselect, so changing the season
                    # selection silently altered the already loaded day: a
                    # different set of points, a different simulation, and
                    # in the extreme case no points at all.
                    st.session_state["anim_params"] = (
                        sel_bear, sel_date_str, tuple(sorted(sel_seasons)),
                        num_alt, int(n_real), int(anim_seed),
                    )

                # An older program version may have left parameters with a
                # different field count in the session. Discard those
                # instead of crashing with a ValueError.
                if len(st.session_state.get("anim_params", ())) != 6:
                    st.session_state.pop("anim_params", None)

                if "anim_params" in st.session_state:
                    (loaded_bear, loaded_date_str, loaded_seasons,
                     loaded_num_alt, loaded_n_real, loaded_seed) = st.session_state["anim_params"]
                    selected_bear_label = f"BEAR {loaded_bear}"

                    with st.spinner(f"Loading {loaded_bear} on {loaded_date_str}..."):
                        try:
                            _res = _load_and_simulate(
                                loaded_bear, loaded_date_str, loaded_seasons,
                                loaded_num_alt, loaded_n_real, loaded_seed,
                            )
                            carpathian_data = _res["carpathian"]
                            alt_geojson = _res["alternative"]
                            sim_geojson = _res["simulated"]
                            sync_warnings = _res["warnings"]
                        except Exception as e:
                            st.error(f"Error while computing the simulation: {e}")

    except Exception as e:
        st.error(f"Error while loading the data: {e}")

    for w in sync_warnings:
        st.warning(w)

    st.markdown("---")
    st.caption(
        "The full path is hidden on start so that the movement only emerges "
        "during playback. It can be shown on the map."
    )

# ============================================================
# Animation map
# ============================================================
if carpathian_data is None:
    st.info("Select bear, season and day in the sidebar, then press **Load**.")
else:
    n_pts = len(carpathian_data.get("points", {}).get("features", []))
    if n_pts == 0:
        st.warning("No GPS points were loaded for this day. Choose a different day.")
    else:
        # Run identifier: stays the same across reruns as long as the
        # simulation does not change, so a change is immediately visible
        # (see _run_id).
        st.caption(
            f"Run ID `{_run_id(sim_geojson)}` - bear {loaded_bear} - {loaded_date_str} - "
            f"{loaded_n_real} realisations - seed {loaded_seed} - "
            f"{loaded_num_alt} alternatives per step"
        )

        anim.render_animation_map(
            carpathian=carpathian_data,
            alternatives=alt_geojson,
            simulated=sim_geojson,
            basemap="Satellite",
            bear_label=selected_bear_label,
            dataset_label="Carpathian Bears - GPS tracking (Romania)",
            source_label=source_label,
            height=900,
        )

        st.markdown("### Data behind the current view")
        _tabs = st.tabs(["Real GPS points", "Simulated paths", "Candidate steps"])
        with _tabs[0]:
            df_real = geojson_to_dataframe(carpathian_data.get("points"))
            st.caption(f"{len(df_real)} real GPS points for {selected_bear_label}, {loaded_date_str}")
            st.dataframe(df_real, width="stretch")
        with _tabs[1]:
            df_sim = geojson_to_dataframe(sim_geojson)
            if df_sim.empty:
                st.info("No simulated paths computed (is the slider at 0?).")
            else:
                st.caption(
                    f"{len(df_sim)} simulated positions across {loaded_n_real} realisations "
                    f"(seed {loaded_seed}). Each realisation is one possible model run, "
                    "not a prediction."
                )
                st.dataframe(df_sim, width="stretch")
        with _tabs[2]:
            df_alt = geojson_to_dataframe(alt_geojson)
            if df_alt.empty:
                st.info("No candidate steps computed.")
            else:
                st.caption(f"{len(df_alt)} candidate steps (movement model)")
                st.dataframe(df_alt, width="stretch")