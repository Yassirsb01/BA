import streamlit as st
import pandas as pd
import os
import datetime
import json
import base64
import io
from datetime import datetime as dt
import streamlit.components.v1 as components

from wildlife_db_mariadb import WildlifeDatabase  # Import the database handler


class JapanDeterrentSystem:
    """
    Japan Bear Deterrent System (MapLibre version)
    - Leaflet/Folium removed
    - Map rendering via MapLibre (WebGL) embedded in Streamlit
    - DB writes are disabled for now (as requested); only read operations are used
    """

    # Safety switch: do NOT write to DB while we are only testing MapLibre replacement
    ENABLE_DB_WRITES = False

    def __init__(self):
        """Initialize the Japan Deterrent System."""
        self.db = WildlifeDatabase()

        # Load data at startup (READ ONLY)
        self.existing_markers = self.load_existing_data()
        self.existing_polygons = self.load_polygon_data()
        self.deterrent_data = self.load_deterrent_data()

        # Determine map center
        if self.deterrent_data is not None and not self.deterrent_data.empty:
            first_point = self.deterrent_data.iloc[0]
            self.map_center = [float(first_point["lat"]), float(first_point["lng"])]
        else:
            # Default center - Central Japan
            self.map_center = [36.2048, 138.2529]

    # Note the _self parameter to make it cacheable
    @st.cache_data(ttl=3600)  # Cache for 1 hour
    def get_image_files(
        _self,
        device_id,
        image_type="device",
        start_date=None,
        end_date=None,
        include_unsuccessful=False,
        daily_time_filter=None,
        limit=100,
        offset=0,
    ):
        """
        Get filtered images for a device from the database
        """
        df = _self.db.get_images(
            device_id=device_id,
            image_type=image_type,
            start_date=start_date,
            end_date=end_date,
            daily_time_filter=daily_time_filter,
            include_unsuccessful=include_unsuccessful,
            limit=limit,
            offset=offset,
        )

        if df.empty:
            return []
        return df.to_dict("records")

    @st.cache_data(ttl=3600)  # Cache for 1 hour
    def format_device_id(_self, raw_device_id):
        """Format device ID with consistent padding"""
        if isinstance(raw_device_id, (int, float)):
            return f"{int(raw_device_id):06d}"
        device_id = str(raw_device_id)
        if device_id.isdigit() and len(device_id) < 6:
            return device_id.zfill(6)
        return device_id

    @st.cache_data(ttl=3600)
    def _get_all_preview_images(_self, deterrent_df_json):
        """Get base64 thumbnail (200×150) of first available device image per deterrent."""
        try:
            from PIL import Image as PILImage
            has_pil = True
        except ImportError:
            has_pil = False

        from io import StringIO
        df = pd.read_json(io.StringIO(deterrent_df_json))
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        result = {}

        for _, row in df.iterrows():
            raw_id = row.get("directory_name", row.get("id", ""))
            formatted_id = _self.format_device_id(raw_id)
            if formatted_id in result:
                continue

            img_df = _self.db.get_images(formatted_id, "device", limit=1)
            if img_df is None or img_df.empty:
                result[formatted_id] = None
                continue

            relative_path = img_df.iloc[0].get("image_path")
            if not relative_path:
                result[formatted_id] = None
                continue

            absolute_path = os.path.join(BASE_DIR, relative_path)
            if not os.path.exists(absolute_path):
                result[formatted_id] = None
                continue

            try:
                if has_pil:
                    img = PILImage.open(absolute_path)
                    img.thumbnail((200, 150))
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=75)
                    b64 = base64.b64encode(buf.getvalue()).decode()
                    result[formatted_id] = f"data:image/jpeg;base64,{b64}"
                else:
                    with open(absolute_path, "rb") as f:
                        raw = f.read()
                    if len(raw) <= 300_000:
                        b64 = base64.b64encode(raw).decode()
                        result[formatted_id] = f"data:image/jpeg;base64,{b64}"
                    else:
                        result[formatted_id] = None
            except Exception:
                result[formatted_id] = None

        return result

    @st.cache_data(ttl=300)
    def _get_all_image_counts(_self, deterrent_df_json):
        from io import StringIO
        df = pd.read_json(io.StringIO(deterrent_df_json))

        # Collect unique formatted device IDs
        device_ids = []
        for _, row in df.iterrows():
            raw_id = row.get("directory_name", row.get("id", ""))
            formatted_id = _self.format_device_id(raw_id)
            if formatted_id not in device_ids:
                device_ids.append(formatted_id)

        # Single batch query instead of N×2 individual queries
        return _self.db.get_image_counts_batch(device_ids)

    
    def load_existing_data(self):
        """Load custom marker data from database"""
        return self.db.get_markers()

    def load_polygon_data(self):
        """Load polygon data from database"""
        return self.db.get_polygons()

    def load_deterrent_data(self):
        """Load deterrent device data from database"""
        return self.db.get_deterrent_devices()

    # -----------------------------
    # MapLibre map rendering (NEW)
    # -----------------------------
    def _df_to_geojson_points(self, df: pd.DataFrame, kind: str):

        if df is None or df.empty:
            return {"type": "FeatureCollection", "features": []}

        # Fetch the counts only ONCE (cached)
        counts_dict = {}
        if kind == "deterrent":
            counts_dict = self._get_all_image_counts(df.to_json())

        features = []

        for _, row in df.iterrows():
            try:
                lat = float(row["lat"])
                lng = float(row["lng"])
            except Exception:
                continue

            # Filter out devices without GPS data:
            # - NULL values from the database become NaN in pandas -> filter out
            # - lat=0, lng=0 means no GPS fix -> filter out
            if pd.isna(lat) or pd.isna(lng):
                continue
            if abs(lat) < 0.01 and abs(lng) < 0.01:
                continue

            props = {"kind": kind}

            if "id" in row:
                props["id"] = str(row["id"])

            if "timestamp" in row:
                props["timestamp"] = str(row["timestamp"])

            if "directory_name" in row:
                props["directory_name"] = str(row["directory_name"])

            # Use the cached counts here
            if kind == "deterrent":
                raw_id = row.get("directory_name", row.get("id", ""))
                formatted_id = self.format_device_id(raw_id)

                counts = counts_dict.get(
                    formatted_id,
                    {"device": 0, "trail": 0}
                )

                props["device_count"] = counts["device"]
                props["trail_count"] = counts["trail"]
                props["formatted_id"] = formatted_id

            features.append(
                {
                    "type": "Feature",
                    "properties": props,
                    "geometry": {
                        "type": "Point",
                        "coordinates": [lng, lat]
                    },
                }
            )

        return {"type": "FeatureCollection", "features": features}

    def _polygons_to_geojson(self, df: pd.DataFrame):
        """
        Convert polygon DF rows to GeoJSON FeatureCollection of Polygon features.
        """
        if df is None or df.empty:
            return {"type": "FeatureCollection", "features": []}

        features = []
        for _, row in df.iterrows():
            polygon_id = str(row.get("polygon_id", ""))
            name = str(row.get("name", ""))

            coords_raw = row.get("coordinates")
            if coords_raw is None:
                continue

            try:
                if isinstance(coords_raw, str):
                    coordinates = json.loads(coords_raw)
                else:
                    coordinates = coords_raw

                if coordinates and coordinates[0] != coordinates[-1]:
                    coordinates = coordinates + [coordinates[0]]

                features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            "polygon_id": polygon_id,
                            "name": name,
                            "timestamp": str(row.get("timestamp", "")),
                        },
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [coordinates],
                        },
                    }
                )
            except Exception:
                continue

        return {"type": "FeatureCollection", "features": features}

    def render_maplibre_map(self, height: int = 520):
        """
        Render MapLibre map with fixes for Popups and REAL Map Style
        """
        deterrents_geojson = self._df_to_geojson_points(self.deterrent_data, kind="deterrent")
        markers_geojson = self._df_to_geojson_points(self.existing_markers, kind="marker")
        polygons_geojson = self._polygons_to_geojson(self.existing_polygons)

        # Preview images (base64 thumbnails) for popup display
        preview_images = {}
        if self.deterrent_data is not None and not self.deterrent_data.empty:
            preview_images = self._get_all_preview_images(self.deterrent_data.to_json())

        center_lng = float(self.map_center[1])
        center_lat = float(self.map_center[0])

        # Street map style (OpenFreeMap Positron)
        style_url = "https://tiles.openfreemap.org/styles/positron"

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
    .controls {{
      position: absolute; top: 10px; left: 10px; z-index: 2;
      background: rgba(255,255,255,0.95); border-radius: 10px;
      padding: 10px; font-family: sans-serif; box-shadow: 0 1px 10px rgba(0,0,0,0.18);
      min-width: 220px;
    }}
    .controls .title {{ font-weight: 700; margin-bottom: 6px; }}
    .controls label {{ display: flex; align-items: center; gap: 8px; margin: 6px 0; cursor: pointer; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; background: #f2f2f2; }}
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="controls">
    <div class="title">Layers</div>
    <label><input type="checkbox" id="toggle-deterrents" checked /> Deterrents <span class="badge" style="color:red">●</span></label>
    <label><input type="checkbox" id="toggle-markers" checked /> Custom markers <span class="badge" style="color:blue">●</span></label>
    <label><input type="checkbox" id="toggle-polygons" checked /> Areas <span class="badge" style="color:green">■</span></label>
  </div>

  <script>
    const deterrentsData = {json.dumps(deterrents_geojson)};
    const markersData    = {json.dumps(markers_geojson)};
    const polygonsData   = {json.dumps(polygons_geojson)};
    const PREVIEW_IMAGES = {json.dumps(preview_images)};

    const map = new maplibregl.Map({{
      container: 'map',
      style: '{style_url}',
      center: [{center_lng}, {center_lat}],
      zoom: 9
    }});

    map.addControl(new maplibregl.NavigationControl(), 'top-right');

    map.on('load', () => {{
      map.addSource('deterrents', {{ type: 'geojson', data: deterrentsData }});
      map.addSource('markers', {{ type: 'geojson', data: markersData }});
      map.addSource('polygons', {{ type: 'geojson', data: polygonsData }});

      map.addLayer({{
        id: 'polygons-fill', type: 'fill', source: 'polygons',
        paint: {{ 'fill-color': '#2a8f2a', 'fill-opacity': 0.20 }}
      }});
      map.addLayer({{
        id: 'polygons-outline', type: 'line', source: 'polygons',
        paint: {{ 'line-color': '#2a8f2a', 'line-width': 2 }}
      }});
      map.addLayer({{
        id: 'deterrents-layer', type: 'circle', source: 'deterrents',
        paint: {{ 'circle-radius': 7, 'circle-color': '#d33', 'circle-stroke-width': 2, 'circle-stroke-color': '#fff' }}
      }});
      map.addLayer({{
        id: 'markers-layer', type: 'circle', source: 'markers',
        paint: {{ 'circle-radius': 7, 'circle-color': '#3186cc', 'circle-stroke-width': 2, 'circle-stroke-color': '#fff' }}
      }});

      // FIXED POPUPS (No Python formatting inside JS strings)
      map.on('click', 'deterrents-layer', (e) => {{
        const p = e.features[0].properties;
        const rawId = p.directory_name || p.id || 'N/A';
        const formattedId = p.formatted_id || rawId;
        const deviceCount = p.device_count || 0;
        const trailCount = p.trail_count || 0;

        const imgSrc = PREVIEW_IMAGES[formattedId];
        const PLACEHOLDER = `<div style="width:100%;height:90px;background:#f3f3f3;display:flex;align-items:center;justify-content:center;border-radius:6px;margin:8px 0;color:#aaa;font-size:13px;">No image available</div>`;
        const imgHtml = imgSrc
          ? `<img src="${{imgSrc}}" style="width:100%;max-width:210px;height:auto;border-radius:6px;margin:8px 0;display:block;" />`
          : PLACEHOLDER;

        new maplibregl.Popup({{ maxWidth: '240px' }}).setLngLat(e.lngLat)
          .setHTML(`
            <div style="min-width:210px;font-family:sans-serif">
              <h3 style="margin:0 0 6px">Deterrent</h3>
              <b>ID:</b> ${{rawId}}<br>
              <b>Device Images:</b> ${{deviceCount}}<br>
              <b>Trail Images:</b> ${{trailCount}}
              ${{imgHtml}}
              <span style="font-size:11px;color:#888">More images in the sidebar</span>
            </div>
          `)
          .addTo(map);
      }});

      map.on('click', 'markers-layer', (e) => {{
        const p = e.features[0].properties;
        new maplibregl.Popup().setLngLat(e.lngLat)
          .setHTML(`<h3>Custom Marker</h3><b>ID:</b> ${{p.id || 'N/A'}}<br><b>Time:</b> ${{p.timestamp || ''}}`)
          .addTo(map);
      }});

      map.on('click', 'polygons-fill', (e) => {{
        const p = e.features[0].properties;
        new maplibregl.Popup().setLngLat(e.lngLat)
          .setHTML(`<h3>Area</h3><b>Name:</b> ${{p.name || 'N/A'}}<br><b>ID:</b> ${{p.polygon_id || ''}}`)
          .addTo(map);
      }});

      // Toggles
      const setupToggle = (id, layerIds) => {{
        document.getElementById(id).addEventListener('change', (e) => {{
          layerIds.forEach(lyr => map.setLayoutProperty(lyr, 'visibility', e.target.checked ? 'visible' : 'none'));
        }});
      }};
      setupToggle('toggle-deterrents', ['deterrents-layer']);
      setupToggle('toggle-markers', ['markers-layer']);
      setupToggle('toggle-polygons', ['polygons-fill', 'polygons-outline']);
    }});
  </script>
</body>
</html>
"""
        components.html(html, height=height, scrolling=False)

    # -----------------------------
    # Sidebar images (Umfangreiche Logik aus Code 1)
    # -----------------------------
    def display_device_images_in_sidebar(self):
        st.sidebar.header("Japan Deterrent Images")

        # Refresh button
        if st.sidebar.button("Refresh Devices", use_container_width=True, type="primary"):
            # Clear the cache
            st.cache_data.clear()
            st.cache_resource.clear()
            # Reload the page
            st.rerun()
        
        st.sidebar.markdown("---")  # separator

        device_ids = []
        if self.deterrent_data is not None and not self.deterrent_data.empty:
            id_col = "id" if "id" in self.deterrent_data.columns else "directory_name"
            if id_col in self.deterrent_data.columns:
                for raw_id in self.deterrent_data[id_col]:
                    formatted_id = self.format_device_id(raw_id)
                    if formatted_id not in device_ids:
                        device_ids.append(formatted_id)
                device_ids.sort()
            else:
                st.sidebar.warning(f"Could not find ID column ('{id_col}') in deterrent data.")

        device_options = ["None"] + device_ids

        if "prev_selected_device" not in st.session_state:
            st.session_state.prev_selected_device = "None"

        selected_device = st.sidebar.selectbox("Select Deterrent ID", options=device_options, index=0)

        if selected_device != st.session_state.prev_selected_device:
            st.session_state.show_device_images = False
            st.session_state.show_trail_images = False
            if "device_page" in st.session_state: del st.session_state["device_page"]
            if "trail_page" in st.session_state: del st.session_state["trail_page"]
            st.session_state.prev_selected_device = selected_device

        if selected_device and selected_device != "None":
            use_filter = False
            start_date = None
            end_date = None
            filter_mode = "Date Range"
            daily_time_filter = None

            with st.sidebar.expander("Date/Time Filters", expanded=False):
                min_year = 2024
                now = datetime.datetime.now()
                max_year = now.year
                years = list(range(min_year, max_year + 1))
                default_end_year_index = years.index(now.year) if now.year in years else len(years)-1

                filter_mode = st.radio("Filter Mode", ["Date Range", "Daily Time Period"], key="filter_mode")

                if filter_mode == "Date Range":

                    col1, col2 = st.columns(2)

                    # -------- START DATE --------
                    with col1:
                        st.write("Start Date:")
                        start_year = st.selectbox("Year", years, key="start_year", index=0)
                        start_month = st.selectbox("Month", range(1, 13), key="start_month", index=0)

                        start_max_days = pd.Timestamp(start_year, start_month, 1).days_in_month
                        start_day_options = range(1, start_max_days + 1)
                        start_day = st.selectbox("Day", start_day_options, key="start_day", index=0)

                    # -------- END DATE --------
                    with col2:
                        st.write("End Date:")
                        end_year = st.selectbox("Year", years, key="end_year", index=default_end_year_index)
                        end_month = st.selectbox("Month", range(1, 13), key="end_month", index=now.month - 1)

                        end_max_days = pd.Timestamp(end_year, end_month, 1).days_in_month
                        end_day_options = range(1, end_max_days + 1)
                        safe_index = min(now.day - 1, end_max_days - 1)
                        end_day = st.selectbox("Day", end_day_options, key="end_day", index=safe_index)

                    st.write("Time Range (24-hour format):")

                    start_hour = st.slider("Start Hour", 0, 23, 0, key="start_hour")
                    end_hour = st.slider("End Hour", 0, 23, 23, key="end_hour")

                    try:
                        start_date = dt(start_year, start_month, start_day, start_hour, 0)
                        end_date = dt(end_year, end_month, end_day, end_hour, 59)

                        if start_date > end_date:
                            st.error("Start date cannot be after end date!")
                            use_filter = False
                        else:
                            use_filter = True
                            st.success(
                                f"Filtering: {start_date.strftime('%Y-%m-%d %H:%M')} "
                                f"to {end_date.strftime('%Y-%m-%d %H:%M')}"
                            )

                    except ValueError:
                        st.error("Invalid date selected!")
                        use_filter = False
                else:  # Daily Time Period mode

                    st.markdown("### Daily Time Period Filter")

                    col1, col2 = st.columns(2)

                    with col1:
                        period_start_year = st.selectbox("From Year", years, key="period_start_year", index=0)
                        period_start_month = st.selectbox("Month", range(1, 13), key="period_start_month", index=0)

                    with col2:
                        period_end_year = st.selectbox("To Year", years, key="period_end_year", index=default_end_year_index)
                        period_end_month = st.selectbox("Month", range(1, 13), key="period_end_month", index=now.month - 1)

                    st.markdown("#### Time of Day to Include:")

                    daily_start_hour = st.slider("Daily Start Hour", 0, 23, 21, key="daily_start_hour")
                    daily_end_hour = st.slider("Daily End Hour", 0, 23, 23, key="daily_end_hour")

                    # Overnight support
                    if daily_start_hour <= daily_end_hour:
                        time_range_text = f"Every day from {daily_start_hour}:00 to {daily_end_hour}:59"
                    else:
                        time_range_text = f"Every night from {daily_start_hour}:00 to {daily_end_hour}:59 (overnight)"

                    st.info(time_range_text)

                    try:
                        start_date = dt(period_start_year, period_start_month, 1, 0, 0)

                        period_end_max_days = pd.Timestamp(period_end_year, period_end_month, 1).days_in_month
                        end_date = dt(period_end_year, period_end_month, period_end_max_days, 23, 59)

                        daily_time_filter = (daily_start_hour, daily_end_hour)

                        use_filter = True

                        st.success(
                            f"Filtering: {start_date.strftime('%Y-%m')} "
                            f"to {end_date.strftime('%Y-%m')} "
                            f"during {time_range_text}"
                        )

                    except ValueError:
                        st.error("Invalid date selection!")
                        use_filter = False

                include_unsuccessful = st.checkbox("Include 'unsuccessful_parsing' images", value=False)
                if st.button("Reset Filters"):
                    st.session_state.show_device_images = False
                    st.rerun()

            # Data Loading
            device_image_list = self.get_image_files(selected_device, "device", start_date=start_date if use_filter else None, end_date=end_date if use_filter else None, daily_time_filter=daily_time_filter)
            trail_image_list = self.get_image_files(selected_device, "trail", start_date=start_date if use_filter else None, end_date=end_date if use_filter else None, daily_time_filter=daily_time_filter)
            

            c1, c2 = st.sidebar.columns(2)
            if c1.button("Load Device Images"): st.session_state.show_device_images = True; st.session_state.show_trail_images = False
            if c2.button("Load Trail Images"): st.session_state.show_trail_images = True; st.session_state.show_device_images = False

            # Image Rendering Logic (Pagination)
            if st.session_state.get("show_device_images"):
                self._render_image_grid(device_image_list, "device")
            if st.session_state.get("show_trail_images"):
                self._render_image_grid(trail_image_list, "trail")
        else:
            st.sidebar.info("Select a deterrent ID to view images")

    def _render_image_grid(self, image_list, prefix):
        st.sidebar.subheader(f"{prefix.capitalize()} Images")

        if not image_list:
            st.sidebar.info("No images found")
            return

        items_per_page = 5
        total_pages = (len(image_list) + items_per_page - 1) // items_per_page
        page_key = f"{prefix}_page"

        if page_key not in st.session_state:
            st.session_state[page_key] = 1

        if total_pages > 1:
            st.session_state[page_key] = st.sidebar.number_input(
                "Page", 1, total_pages, key=f"ni_{prefix}"
            )

        start_idx = (st.session_state[page_key] - 1) * items_per_page

        for img_data in image_list[start_idx : start_idx + items_per_page]:
            # Check whether image_bytes is present (from the unified table)
            if 'image_bytes' in img_data and img_data['image_bytes']:
                # Image is stored as a BLOB
                try:
                    import base64
                    from PIL import Image as PILImage
                    
                    img_bytes = img_data['image_bytes']
                    img = PILImage.open(io.BytesIO(img_bytes))
                    
                    st.sidebar.image(
                        img,
                        caption=f"{img_data.get('filename')} (Quelle: {img_data.get('source', 'unknown')})",
                        use_container_width=True
                    )
                except Exception as e:
                    st.sidebar.error(f"Error loading image: {e}")
            
            # Legacy path: the image exists as a file (fallback)
            elif 'image_path' in img_data and img_data['image_path']:
                BASE_DIR = os.path.dirname(os.path.abspath(__file__))
                relative_path = img_data.get("image_path")
                absolute_path = os.path.join(BASE_DIR, relative_path)

                if os.path.exists(absolute_path):
                    st.sidebar.image(
                        absolute_path,
                        caption=img_data.get("filename"),
                        use_container_width=True
                    )
                else:
                    st.sidebar.warning(f"Image file not found: {absolute_path}")
            else:
                st.sidebar.warning(f"No image data for: {img_data.get('filename')}")

    # -----------------------------
    # Main page rendering (full UI)
    # -----------------------------
    def display_japan_deterrent_section(self):
        st.title("Interactive Bear Deterrent Mapping System (MapLibre)")
        tab1, tab2 = st.tabs(["Markers", "Areas"])

        with tab1:
            st.subheader("Deterrent Devices Map (MapLibre)")
            st.info("Layer toggles are available on the map (top-left). Zoom controls are on the top-right.")
            self.render_maplibre_map(height=520)
            self.display_device_images_in_sidebar()

            st.markdown("---")
            st.subheader("Editing (disabled for now)")
            st.warning("DB write actions are disabled while we are only testing the MapLibre replacement.")

            col1, col2 = st.columns(2)
            col1.button("Save New Markers & Areas", disabled=not self.ENABLE_DB_WRITES, width=True)
            col2.button("Delete All Markers", disabled=not self.ENABLE_DB_WRITES, width=True)

            st.subheader("Manage Markers (read-only view)")
            if not self.existing_markers.empty:
                st.dataframe(self.existing_markers[["id", "lat", "lng", "timestamp"]], width=True)
            else:
                st.info("No custom markers found.")

        with tab2:
            st.subheader("Areas Management (read-only view)")
            if not self.existing_polygons.empty:
                for _, row in self.existing_polygons.iterrows():
                    with st.expander(f"Area: {row.get('name', 'Unnamed')} (ID: {row.get('polygon_id')})"):
                        st.write(f"Created: {row.get('timestamp')}")
                        st.json(row.get('coordinates'))
            else:
                st.info("No areas defined yet.")

# Standalone execution
if __name__ == "__main__":
    JapanDeterrentSystem().display_japan_deterrent_section()