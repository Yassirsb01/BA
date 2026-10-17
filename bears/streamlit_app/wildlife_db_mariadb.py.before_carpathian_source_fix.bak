#!/usr/bin/env python3
"""
Enhanced wildlife_db_mariadb.py with FAST batch processing
Complete version based on your original file with optimizations added
"""

import mysql.connector
import pandas as pd
import os
import json
from datetime import datetime
import numpy as np
from pyproj import Transformer
import time

# Connection settings. Environment variables take precedence over the
# defaults below, so the deployment can supply its own credentials without
# any code change:
#
#   WILDLIFE_DB_HOST, WILDLIFE_DB_PORT, WILDLIFE_DB_USER,
#   WILDLIFE_DB_PASSWORD, WILDLIFE_DB_NAME
#
# The defaults reproduce the previous hard-coded values so that existing
# setups keep working unchanged. Before deploying, the credentials should
# be supplied through the environment rather than left in the source; see
# the deployment section of README.md.
DB_HOST = os.environ.get("WILDLIFE_DB_HOST", "172.20.39.9")
DB_PORT = int(os.environ.get("WILDLIFE_DB_PORT", "3306"))
DB_USER = os.environ.get("WILDLIFE_DB_USER", "ursus")
DB_PASSWORD = os.environ.get("WILDLIFE_DB_PASSWORD", "thibetanus")
DB_NAME = os.environ.get("WILDLIFE_DB_NAME", "ursus")


class WildlifeDatabase:
    def __init__(self, db_path_or_host=DB_HOST, port=DB_PORT, user=DB_USER,
                 password=DB_PASSWORD, database=DB_NAME):
        """Initialize the database connection to MariaDB"""
        # Add db_path attribute for backward compatibility
        self.db_path = "wildlife_data.db"

        # Check if the first parameter is a string containing ".db"
        if isinstance(db_path_or_host, str) and ".db" in db_path_or_host:
            print(f"Note: SQLite path '{db_path_or_host}' detected, but using MariaDB connection instead.")
            self.db_path = db_path_or_host
            self.db_config = {
                'host': DB_HOST,
                'port': DB_PORT,
                'user': DB_USER,
                'password': DB_PASSWORD,
                'database': DB_NAME,
                'connection_timeout': 15,
            }
        else:
            # Normal MariaDB initialization
            self.db_config = {
                'host': db_path_or_host,
                'port': port,
                'user': user,
                'password': password,
                'database': database,
                'connection_timeout': 15,
            }
        
        # Initialize the coordinate transformer
        self.transformer = Transformer.from_crs("EPSG:3844", "EPSG:4326", always_xy=True)
    
    def _get_connection(self):
        """Get a connection to the MariaDB database"""
        return mysql.connector.connect(**self.db_config)

    def is_reachable(self, timeout_sec: float = 6.0) -> bool:
        """
        Report whether the database answers within timeout_sec seconds.

        The time limit is enforced by a background thread rather than by
        connection_timeout alone. A silently dropped packet, which is what
        happens when the host is only reachable through the university VPN
        and the VPN is down, makes the connection attempt wait for the full
        connection_timeout of 15 seconds. In an interactive page that runs
        again on every click, that delay is noticeable on every single
        interaction, so the caller needs a shorter, hard bound.

        The same pattern is used by check_db_reachable_bounded() in
        activity_overlap.py; signal.alarm() is not an option because it
        does not exist on Windows.

        Returns True only if a connection was opened and closed within the
        time limit. The probing thread is a daemon: if it is still running
        when the limit passes it no longer blocks the caller.
        """
        import threading

        result = {"ok": False}

        def _try_connect():
            try:
                conn = self._get_connection()
                conn.close()
                result["ok"] = True
            except Exception:
                result["ok"] = False

        t = threading.Thread(target=_try_connect, daemon=True)
        t.start()
        t.join(timeout_sec)
        if t.is_alive():
            return False
        return result["ok"]

    def initialize_db(self):
        """Initialize the database with all required tables"""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Create all tables with MariaDB syntax
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS deterrent_devices (
                    id VARCHAR(255) PRIMARY KEY,
                    directory_name VARCHAR(255),
                    lat FLOAT,
                    lng FLOAT
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS markers (
                    id VARCHAR(255) PRIMARY KEY,
                    timestamp VARCHAR(255),
                    lat FLOAT,
                    lng FLOAT
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS polygons (
                    polygon_id VARCHAR(255) PRIMARY KEY,
                    timestamp VARCHAR(255),
                    name VARCHAR(255),
                    coordinates TEXT
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS image_metadata (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    device_id VARCHAR(255),
                    image_path VARCHAR(1024),
                    image_type VARCHAR(50),
                    filename VARCHAR(255),
                    timestamp VARCHAR(255),
                    parsed_successfully BOOLEAN,
                    FOREIGN KEY (device_id) REFERENCES deterrent_devices(id)
                )
            ''')
            
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_image_device ON image_metadata(device_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_image_timestamp ON image_metadata(timestamp)')
            
            # Create bear tracking tables
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bears_tracking (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    bear_id VARCHAR(255),
                    timestamp VARCHAR(255),
                    x FLOAT,
                    y FLOAT,
                    lat FLOAT,
                    lng FLOAT,
                    season_code VARCHAR(50),
                    season VARCHAR(255),
                    sex VARCHAR(50),
                    age VARCHAR(50),
                    is_daytime BOOLEAN
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bears_mcp (
                    id INT AUTO_INCREMENT PRIMARY KEY, 
                    bear_id VARCHAR(255),
                    area FLOAT,
                    sex VARCHAR(50),
                    age VARCHAR(50),
                    num_gmu INT,
                    stage VARCHAR(50)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bears_core_area (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    bear_id VARCHAR(255),
                    sex VARCHAR(50),
                    age VARCHAR(50),
                    area FLOAT
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bears_kde (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    bear_id VARCHAR(255),
                    area FLOAT,
                    sex VARCHAR(50),
                    age VARCHAR(50),
                    num_gmu INT,
                    stage VARCHAR(50)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bears_seasonal_mcp (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    bear_id VARCHAR(255),
                    area FLOAT,
                    season VARCHAR(255)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bears_daily_displacement (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    bear_id VARCHAR(255),
                    x FLOAT,
                    y FLOAT,
                    lat FLOAT,
                    lng FLOAT,
                    date VARCHAR(255),
                    distance FLOAT,
                    season VARCHAR(255),
                    altitude FLOAT
                )
            ''')
            
            conn.commit()
            print("Database schema initialized successfully")
            return True
        except Exception as e:
            print(f"!!! Error during initialize_db: {e}")
            if conn: 
                conn.rollback()
            return False
        finally:
            if 'cursor' in locals() and cursor: 
                cursor.close()
            if 'conn' in locals() and conn: 
                conn.close()

    def execute_query(self, query, params=None):
        """Execute a query and return results as a list of dictionaries"""
        conn = None
        result = []
        try:
            conn = self._get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(query, params or ())
            result = cursor.fetchall()
            cursor.close()
        except Exception as e:
            print(f"Error executing query: {e}")
            raise
        finally:
            if conn:
                conn.close()
        return result

    def execute_update(self, query, params=None):
        """Execute an update query and return the number of affected rows"""
        conn = None
        rows_affected = 0
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(query, params or ())
            rows_affected = cursor.rowcount
            conn.commit()
            cursor.close()
        except Exception as e:
            print(f"Error executing update: {e}")
            if conn: 
                conn.rollback()
        finally:
            if conn: 
                conn.close()
        return rows_affected

    def execute_scalar(self, query, params=None):
        """Execute a query that returns a single value"""
        conn = None
        value = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(query, params or ())
            result = cursor.fetchone()
            if result:
                value = result[0]
            cursor.close()
        except Exception as e:
            print(f"Error executing scalar query: {e}")
        finally:
            if conn: 
                conn.close()
        return value

    def import_deterrent_devices(self, csv_path="data/device_data/deterrent_devices.csv", batch_size=1000):
        """FAST batch import for deterrent devices"""
        if not os.path.exists(csv_path): 
            print(f"CSV file not found: {csv_path}")
            return False
            
        try:
            df = pd.read_csv(csv_path, dtype={'Directory name': str})
            print(f"Read CSV with columns: {df.columns.tolist()}")
            print(f"Found {len(df)} deterrent devices in CSV")
        except Exception as e: 
            print(f"Error reading CSV {csv_path}: {e}")
            return False
            
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            print("Dropping deterrent_devices table (if exists)...")
            cursor.execute("DROP TABLE IF EXISTS deterrent_devices")
            
            print("Creating deterrent_devices table...")
            cursor.execute('''
                CREATE TABLE deterrent_devices (
                    id VARCHAR(255) PRIMARY KEY,
                    directory_name VARCHAR(255),
                    lat FLOAT,
                    lng FLOAT
                )
            ''')
            print("Table 'deterrent_devices' created.")
            
            # Prepare batch data
            batch_data = []
            for _, row in df.iterrows():
                if 'Directory name' not in row or pd.isna(row['Directory name']) or 'lat' not in row or 'lng' not in row:
                    continue
                    
                directory_name_raw = str(row['Directory name']).strip()
                id_cleaned = directory_name_raw
                
                if '.' in id_cleaned:
                    try:
                       id_float = float(id_cleaned)
                       if id_float == int(id_float): 
                           id_cleaned = str(int(id_float))
                    except ValueError: 
                        pass
                
                batch_data.append((id_cleaned, id_cleaned, row['lat'], row['lng']))
            
            # Batch insert
            print("Starting batch insertions...")
            insert_query = "INSERT INTO deterrent_devices (id, directory_name, lat, lng) VALUES (%s, %s, %s, %s)"
            
            successful_inserts = 0
            start_time = time.time()
            
            for i in range(0, len(batch_data), batch_size):
                batch = batch_data[i:i + batch_size]
                try:
                    cursor.executemany(insert_query, batch)
                    successful_inserts += len(batch)
                except Exception as e:
                    print(f"Error in batch {i//batch_size + 1}: {e}")
            
            print("Attempting to commit insertions...")
            conn.commit()
            print("Commit successful.")
            
            elapsed_time = time.time() - start_time
            rate = successful_inserts / elapsed_time if elapsed_time > 0 else 0
            
            cursor.execute("SELECT COUNT(*) FROM deterrent_devices")
            post_commit_count = cursor.fetchone()[0]
            print(f"Verification Query: Found {post_commit_count} records in table immediately after commit.")
            print(f"Fast batch insert completed: {successful_inserts} records in {elapsed_time:.2f}s ({rate:.0f} records/sec)")
            
            if post_commit_count == successful_inserts:
                print(f"Table rebuilt successfully with {post_commit_count} records.")
                return True
            else:
                print(f"!!! Mismatch: Expected {successful_inserts} records, but found {post_commit_count} after commit!")
                return False
                
        except Exception as e:
            print(f"!!! Error during deterrent devices import process: {e}")
            if conn: 
                conn.rollback()
            return False
        finally:
            if 'cursor' in locals() and cursor: 
                cursor.close()
            if conn: 
                conn.close()

    def get_deterrent_devices(self):
        """Get deterrent devices from database"""
        # CAST id to INT so that ordering is numeric rather than lexicographic
        results = self.execute_query(
            "SELECT * FROM deterrent_devices ORDER BY CAST(id AS UNSIGNED)"
        )
        df = pd.DataFrame(results) if results else pd.DataFrame()
        if 'id' in df.columns:
            df['id'] = df['id'].astype(str)
        if 'directory_name' in df.columns:
            df['directory_name'] = df['directory_name'].astype(str)
        return df

    def import_markers(self, csv_path="data/device_data/artificial_device_coordinates.csv"):
        """Import markers from CSV"""
        if not os.path.exists(csv_path): 
            print(f"Markers CSV file not found: {csv_path}. Skipping markers import.")
            return True
            
        try: 
            df = pd.read_csv(csv_path, dtype={'id': str})
        except Exception as e: 
            print(f"Error reading markers CSV {csv_path}: {e}")
            return False
            
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Ensure table exists
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS markers (
                    id VARCHAR(255) PRIMARY KEY,
                    timestamp VARCHAR(255),
                    lat FLOAT,
                    lng FLOAT
                )
            ''')
            
            print(f"Importing markers from {csv_path}. Existing markers will be kept (duplicates skipped).")
            inserted_count = 0
            skipped_count = 0
            
            for _, row in df.iterrows():
                marker_id = str(row['id']) if pd.notna(row['id']) else None
                if not marker_id:
                    skipped_count += 1
                    continue
                    
                try:
                    if 'timestamp' not in row or 'lat' not in row or 'lng' not in row:
                        skipped_count += 1
                        continue
                        
                    # Use INSERT IGNORE for MariaDB to skip existing records
                    cursor.execute(
                        "INSERT IGNORE INTO markers (id, timestamp, lat, lng) VALUES (%s, %s, %s, %s)",
                        (marker_id, row['timestamp'], row['lat'], row['lng'])
                    )
                    
                    if cursor.rowcount > 0:
                        inserted_count += 1
                    else:
                        skipped_count += 1
                        
                except Exception as e:
                    print(f"Error inserting marker {marker_id}: {e}")
                    skipped_count += 1
                    
            conn.commit()
            print(f"Attempted marker import: {inserted_count} new markers inserted, {skipped_count} skipped (duplicates/errors).")
            return True
            
        except Exception as e:
            print(f"!!! Error during markers import process: {e}")
            if conn: 
                conn.rollback()
            return False
        finally:
            if 'cursor' in locals() and cursor: 
                cursor.close()
            if conn: 
                conn.close()

    def get_markers(self):
        """Get markers from database"""
        results = self.execute_query("SELECT * FROM markers ORDER BY id")
        df = pd.DataFrame(results) if results else pd.DataFrame()
        if 'id' in df.columns:
            df['id'] = df['id'].astype(str)
        return df

    def import_polygons(self, csv_path="data/areas/user_drawn_area_cities.csv"):
        """Import polygon data from CSV"""
        if not os.path.exists(csv_path): 
            print(f"Polygons CSV file not found: {csv_path}. Skipping polygons import.")
            return True
            
        try: 
            df = pd.read_csv(csv_path, dtype={'polygon_id': str})
        except Exception as e: 
            print(f"Error reading polygons CSV {csv_path}: {e}")
            return False
            
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            print(f"Importing polygons from {csv_path}. Existing polygons will be kept (duplicates skipped).")
            inserted_count = 0
            skipped_count = 0
            
            for _, row in df.iterrows():
                 polygon_id = str(row['polygon_id']) if pd.notna(row['polygon_id']) else None
                 if not polygon_id:
                     skipped_count += 1
                     continue
                     
                 try:
                     if 'timestamp' not in row or 'name' not in row or 'coordinates' not in row:
                         skipped_count += 1
                         continue
                         
                     cursor.execute(
                         "INSERT IGNORE INTO polygons (polygon_id, timestamp, name, coordinates) VALUES (%s, %s, %s, %s)",
                         (polygon_id, row['timestamp'], row['name'], row['coordinates'])
                     )
                     
                     if cursor.rowcount > 0:
                         inserted_count += 1
                     else:
                         skipped_count += 1
                         
                 except Exception as e:
                     print(f"Error inserting polygon {polygon_id}: {e}")
                     skipped_count += 1
                     
            conn.commit()
            print(f"Attempted polygon import: {inserted_count} new polygons inserted, {skipped_count} skipped (duplicates/errors).")
            return True
            
        except Exception as e:
            print(f"!!! Error during polygons import process: {e}")
            if conn: 
                conn.rollback()
            return False
        finally:
            if 'cursor' in locals() and cursor: 
                cursor.close()
            if conn: 
                conn.close()

    def get_polygons(self):
        """Get polygons from database"""
        results = self.execute_query("SELECT * FROM polygons ORDER BY polygon_id")
        df = pd.DataFrame(results) if results else pd.DataFrame()

        if 'polygon_id' in df.columns:
            df['polygon_id'] = df['polygon_id'].astype(str)
        if 'name' in df.columns:
            df['name'] = df['name'].astype(str)

        if not df.empty and 'coordinates' in df.columns:
            def safe_json_loads(x):
                if isinstance(x, str):
                    try:
                        return json.loads(x)
                    except json.JSONDecodeError:
                        return None
                return x
            df['coordinates'] = df['coordinates'].apply(safe_json_loads)

        return df

    def index_image_files(self, base_folder="data/bear_pictures", reindex=False):
        """Scan directory and index image files for MariaDB"""
        start_time = datetime.now()
        conn = None
        images_indexed = 0
        folders_processed = 0
        skipped_files = 0
        total_files_found = 0

        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            if reindex:
                print("Reindexing: Clearing existing image metadata...")
                cursor.execute("DELETE FROM image_metadata")
                conn.commit()
                print("Existing image metadata cleared.")

            if not os.path.isdir(base_folder):
                 print(f"Error: Base image folder '{base_folder}' not found.")
                 return 0

            print(f"Starting image scan in '{base_folder}'...")
            try:
                device_dirs = os.listdir(base_folder)
            except OSError as e_list_base:
                print(f"!!! OS error listing base directory {base_folder}: {e_list_base}")
                return 0

            print(f"Found {len(device_dirs)} items in base folder.")

            for device_dir in device_dirs:
                device_path = os.path.join(base_folder, device_dir)
                if not os.path.isdir(device_path):
                    print(f"  Skipping non-directory item: {device_dir}")
                    continue

                folders_processed += 1
                print(f"\nProcessing Device Folder: {device_path}")
                device_id_raw = str(device_dir).strip()
                device_id_cleaned = device_id_raw
                
                # Clean ID
                if '.' in device_id_cleaned:
                    try:
                       id_float = float(device_id_cleaned)
                       if id_float == int(id_float): 
                           device_id_cleaned = str(int(id_float))
                    except ValueError: 
                        pass
                print(f"  Device ID (Cleaned): {device_id_cleaned}")

                # Function to process images in a subfolder
                def process_image_folder(image_folder_path, image_type):
                    nonlocal images_indexed, skipped_files, total_files_found
                    print(f"  Scanning Subfolder: {image_folder_path} (Type: {image_type})")
                    if os.path.isdir(image_folder_path):
                        files_processed_in_folder = 0
                        try:
                            files_in_folder = os.listdir(image_folder_path)
                            print(f"    Found {len(files_in_folder)} items.")
                            for img_file in files_in_folder:
                                total_files_found += 1
                                file_path = os.path.join(image_folder_path, img_file)
                                if os.path.isfile(file_path) and img_file.lower().endswith(('.jpg', '.jpeg', '.png')):
                                    files_processed_in_folder += 1
                                    is_unsuccessful = "unsuccessful_parsing" in img_file and image_type == "trail_processed"
                                    parsed_successfully = not is_unsuccessful
                                    storage_image_type = "trail" if image_type == "trail_processed" else "device"
                                    timestamp = self._extract_timestamp_from_filename(img_file, image_type)
                                    img_path = file_path.replace("\\", "/")
                                    try:
                                        cursor.execute(
                                            """INSERT IGNORE INTO image_metadata
                                               (device_id, image_path, image_type, filename, timestamp, parsed_successfully)
                                               VALUES (%s, %s, %s, %s, %s, %s)""",
                                            (device_id_cleaned, img_path, storage_image_type, img_file, timestamp, parsed_successfully)
                                        )
                                        images_indexed += 1
                                    except Exception as e_insert:
                                         print(f"      !!! Error inserting metadata for {img_path}: {e_insert}")
                                         skipped_files += 1
                                else:
                                     skipped_files += 1
                            print(f"    Finished processing {files_processed_in_folder} potential images in this subfolder.")
                        except OSError as e_os:
                            print(f"    !!! OS error reading folder {image_folder_path}: {e_os}")
                            skipped_files += 1
                    else:
                         print(f"    Subfolder not found or not a directory: {image_folder_path}")

                # Process image folders
                process_image_folder(os.path.join(device_path, "device"), "device")
                process_image_folder(os.path.join(device_path, "trail_processed"), "trail_processed")

            # Commit after processing ALL device folders
            print("\nCommitting all indexed image metadata...")
            conn.commit()
            print("Image metadata commit successful.")

        except Exception as e:
             print(f"!!! Error during image indexing main process: {e}")
             if conn: 
                 conn.rollback()
        finally:
             if conn:
                 print("Closing database connection for image indexing.")
                 conn.close()

        elapsed_time = (datetime.now() - start_time).total_seconds()
        print(f"\n--- Image Indexing Summary ---")
        print(f"Processed {folders_processed} potential device folders.")
        print(f"Encountered {total_files_found} total file system items in relevant subfolders.")
        print(f"Successfully indexed {images_indexed} images.")
        print(f"Skipped {skipped_files} non-image files or files causing errors.")
        print(f"Indexing completed in {elapsed_time:.2f} seconds.")
        print(f"------------------------------")
        return images_indexed

    def _extract_timestamp_from_filename(self, filename, image_type):
        """Extract timestamp from filename"""
        logic_type = "trail" if image_type == "trail_processed" else image_type
        try:
            if logic_type == "trail":
                if "unsuccessful_parsing" in filename: 
                    return None
                base_name = os.path.splitext(filename)[0]
                parts = base_name.split('.')
                date_part = base_name
                if len(parts) >= 4 and all(p.isdigit() for p in parts[-4:]):
                    date_part = ".".join(parts[-4:])
                dt_obj = datetime.strptime(date_part, "%Y.%m.%d.%H%M")
                return dt_obj.isoformat()
            elif logic_type == "device":
                parts = filename.split('_')
                if len(parts) >= 3:
                    date_str = parts[2]
                    date_str_cleaned = "".join(filter(lambda c: c.isdigit() or c == '.', date_str))
                    dt_obj = datetime.strptime(date_str_cleaned, "%Y.%m.%d.%H%M")
                    return dt_obj.isoformat()
        except (ValueError, IndexError, TypeError): 
            pass
        return None

    def _transform_coordinates(self, x, y):
        """Transform coordinates from EPSG:3844 to WGS84"""
        if pd.isna(x) or pd.isna(y):
            return None, None
        try:
            lng, lat = self.transformer.transform(x, y)
            return lat, lng
        except Exception as e:
            print(f"Error transforming coordinates ({x}, {y}): {e}")
            return None, None

    def import_bears_tracking_data(self, csv_path=None):
        """Import Carpathian Bears tracking data"""
        if csv_path and os.path.exists(csv_path):
            # Use the provided processed CSV file
            return self._import_bears_from_processed_csv(csv_path)
        else:
            # Import from individual CSV files
            return self._import_bears_from_individual_files()

    def _import_bears_from_processed_csv(self, csv_path):
        """Import bears tracking data from a single processed CSV file"""
        print(f"Importing bears tracking data from processed file: {csv_path}")
        
        try:
            df = pd.read_csv(csv_path, dtype={
                'X': float, 'Y': float, 'Name': str, 
                'Season': str, 'Season2': str, 'Sex': str, 'age': str
            })
            
            # Handle timestamp column
            timestamp_col = None
            for col in ['Timestamp', 'timestamp', 'DateTime', 'Time']:
                if col in df.columns:
                    timestamp_col = col
                    break
                    
            if timestamp_col:
                df[timestamp_col] = pd.to_datetime(df[timestamp_col], errors='coerce')
                df.dropna(subset=[timestamp_col], inplace=True)
                df.rename(columns={timestamp_col: 'Timestamp'}, inplace=True)
            
            print(f"Read {len(df)} bear tracking records from {csv_path}")
        except Exception as e:
            print(f"Error reading bears CSV {csv_path}: {e}")
            return False
        
        return self._insert_bears_tracking_data(df)

    def _import_bears_from_individual_files(self):
        """Import bears tracking data from individual CSV files"""
        tracking_files = [
            "data/animal_data/carpathian_bears/1_bears_RO.csv",
            "data/animal_data/carpathian_bears/2_bears_RO_seasons.csv"
        ]
        
        all_data = []
        
        for file_path in tracking_files:
            if os.path.exists(file_path):
                print(f"Reading {file_path}...")
                try:
                    df = pd.read_csv(file_path, dtype={
                        'X': float, 'Y': float, 'Name': str,
                        'Season': str, 'Season2': str, 'Sex': str, 'age': str
                    })
                    
                    # Handle timestamp column
                    timestamp_col = None
                    for col in ['Timestamp', 'timestamp', 'DateTime', 'Time']:
                        if col in df.columns:
                            timestamp_col = col
                            break
                            
                    if timestamp_col:
                        df[timestamp_col] = pd.to_datetime(df[timestamp_col], errors='coerce')
                        df.dropna(subset=[timestamp_col], inplace=True)
                        df.rename(columns={timestamp_col: 'Timestamp'}, inplace=True)
                    
                    all_data.append(df)
                    print(f"Read {len(df)} records from {file_path}")
                    
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")
                    continue
            else:
                print(f"File not found: {file_path}")
        
        if not all_data:
            print("No tracking data files could be processed")
            return False
        
        # Combine all data
        combined_df = pd.concat(all_data, ignore_index=True)
        print(f"Combined {len(combined_df)} total tracking records")
        
        return self._insert_bears_tracking_data(combined_df)

    def _insert_bears_tracking_data(self, df, limit_records=None, batch_size=5000):
        """FAST batch insert for bears tracking data"""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Clear existing data
            print("Clearing existing bears_tracking data...")
            cursor.execute("DELETE FROM bears_tracking")
            conn.commit()
            
            # Limit records if specified
            if limit_records:
                df = df.head(limit_records)
                print(f"Limited to first {len(df)} records for testing")
            
            print(f"Processing {len(df)} records in batches of {batch_size}...")
            
            # Prepare all data first (vectorized operations)
            print("Preprocessing data...")
            start_prep = time.time()
            
            # Transform coordinates in bulk using vectorized operations
            print("Transforming coordinates...")
            valid_coords = df[['X', 'Y']].notna().all(axis=1)
            lat_lng_data = np.full((len(df), 2), None, dtype=object)
            
            if valid_coords.any():
                valid_x = df.loc[valid_coords, 'X'].values
                valid_y = df.loc[valid_coords, 'Y'].values
                
                # Batch coordinate transformation
                try:
                    lng_vals, lat_vals = self.transformer.transform(valid_x, valid_y)
                    lat_lng_data[valid_coords.values, 0] = lat_vals
                    lat_lng_data[valid_coords.values, 1] = lng_vals
                except Exception as e:
                    print(f"Coordinate transformation error: {e}")
            
            # Prepare timestamp data
            print("Processing timestamps...")
            timestamp_data = []
            is_daytime_data = []
            
            for _, row in df.iterrows():
                ts_iso = None
                is_daytime = False
                
                if 'Timestamp' in row and pd.notna(row['Timestamp']):
                    try:
                        ts_iso = row['Timestamp'].isoformat()
                        hour = row['Timestamp'].hour
                        is_daytime = 6 <= hour < 20
                    except:
                        pass
                
                timestamp_data.append(ts_iso)
                is_daytime_data.append(is_daytime)
            
            prep_time = time.time() - start_prep
            print(f"Preprocessing completed in {prep_time:.2f} seconds")
            
            # Prepare batch data
            print("Preparing batch insert data...")
            batch_data = []
            
            for i, (_, row) in enumerate(df.iterrows()):
                lat, lng = lat_lng_data[i] if lat_lng_data[i][0] is not None else (None, None)
                
                record = (
                    str(row.get('Name', '')).strip() if pd.notna(row.get('Name')) else None,
                    timestamp_data[i],
                    row.get('X'), row.get('Y'), lat, lng,
                    str(row.get('Season', '')).strip() if pd.notna(row.get('Season')) else None,
                    str(row.get('Season2', '')).strip() if pd.notna(row.get('Season2')) else None,
                    str(row.get('Sex', '')).strip() if pd.notna(row.get('Sex')) else None,
                    str(row.get('age', '')).strip() if pd.notna(row.get('age')) else None,
                    is_daytime_data[i]
                )
                batch_data.append(record)
            
            # Batch insert
            print("Starting batch inserts...")
            insert_query = """
                INSERT INTO bears_tracking 
                (bear_id, timestamp, x, y, lat, lng, season_code, season, sex, age, is_daytime) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            total_inserted = 0
            start_insert = time.time()
            
            # Process in batches
            for i in range(0, len(batch_data), batch_size):
                batch = batch_data[i:i + batch_size]
                
                try:
                    cursor.executemany(insert_query, batch)
                    total_inserted += len(batch)
                    
                    if i % (batch_size * 2) == 0:  # Progress every 2 batches
                        elapsed = time.time() - start_insert
                        rate = total_inserted / elapsed if elapsed > 0 else 0
                        print(f"Inserted {total_inserted}/{len(batch_data)} records ({rate:.0f} records/sec)")
                    
                except Exception as e:
                    print(f"Error in batch {i//batch_size + 1}: {e}")
                    continue
            
            # Commit all at once
            print("Committing transaction...")
            conn.commit()
            
            insert_time = time.time() - start_insert
            total_time = prep_time + insert_time
            rate = total_inserted / total_time if total_time > 0 else 0
            
            print(f"Batch insert completed:")
            print(f"  - Records inserted: {total_inserted}")
            print(f"  - Preprocessing time: {prep_time:.2f}s")
            print(f"  - Insert time: {insert_time:.2f}s")
            print(f"  - Total time: {total_time:.2f}s")
            print(f"  - Average rate: {rate:.0f} records/second")
            
            return total_inserted > 0
            
        except Exception as e:
            print(f"!!! Error during fast bears tracking import: {e}")
            if conn: 
                conn.rollback()
            return False
        finally:
            if 'cursor' in locals() and cursor: 
                cursor.close()
            if conn: 
                conn.close()

    # Keep all your existing methods here (get_bears_list, get_seasonal_data, etc.)
    def get_bears_list(self):
        """Get a list of all bears in the database with basic information"""
        try:
            query = """
            SELECT DISTINCT 
                bear_id, 
                sex,
                age,
                COUNT(*) as point_count
            FROM bears_tracking
            WHERE bear_id IS NOT NULL
            GROUP BY bear_id, sex, age
            ORDER BY bear_id
            """
            results = self.execute_query(query)
            df = pd.DataFrame(results) if results else pd.DataFrame()
            return df
        except Exception as e:
            print(f"!!! Error getting bears list: {e}")
            return pd.DataFrame()

    def get_bear_data(self, bear_id=None, start_date=None, end_date=None, season=None):
        """Get tracking data for one or all bears with filtering options"""
        try:
            query = "SELECT * FROM bears_tracking WHERE 1=1"
            params = []
            
            if bear_id:
                query += " AND bear_id = %s"
                params.append(bear_id)
                
            if start_date:
                start_iso = start_date.isoformat() if isinstance(start_date, datetime) else start_date
                query += " AND timestamp >= %s"
                params.append(start_iso)
                
            if end_date:
                end_iso = end_date.isoformat() if isinstance(end_date, datetime) else end_date
                query += " AND timestamp <= %s"
                params.append(end_iso)
                
            if season:
                query += " AND season = %s"
                params.append(season)
                
            query += " ORDER BY bear_id, timestamp"
            
            results = self.execute_query(query, params)
            df = pd.DataFrame(results) if results else pd.DataFrame()
            
            if not df.empty and 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                
            return df
        except Exception as e:
            print(f"!!! Error getting bear data: {e}")
            return pd.DataFrame()

    def get_date_range(self, table_name, date_column):
        """Get the minimum and maximum date from a specific column in a table"""
        try:
            query = f"SELECT MIN({date_column}), MAX({date_column}) FROM {table_name} WHERE {date_column} IS NOT NULL"
            
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(query)
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if result and result[0] and result[1]:
                try:
                    min_date = pd.to_datetime(result[0]).date()
                    max_date = pd.to_datetime(result[1]).date()
                    return min_date, max_date
                except Exception as e:
                    print(f"Error parsing dates from database: {e}")
                    return datetime(2018, 1, 1).date(), datetime(2023, 12, 31).date()
            else:
                print(f"No valid date range found in database for {table_name}.{date_column}")
                return datetime(2018, 1, 1).date(), datetime(2023, 12, 31).date()
        except Exception as e:
            print(f"Error processing dates in get_date_range: {e}")
            return datetime(2018, 1, 1).date(), datetime(2023, 12, 31).date()

    def get_distinct_values(self, table_name, column_name):
        """Get distinct values from a specific column in a table"""
        try:
            query = f"SELECT DISTINCT {column_name} FROM {table_name} WHERE {column_name} IS NOT NULL"
            results = self.execute_query(query)
            distinct_values = [row[column_name] for row in results] if results else []
            return distinct_values
        except Exception as e:
            print(f"Database error in get_distinct_values: {e}")
            return []

    # Add other essential methods you need (save_marker, delete_marker, etc.)
    def save_marker(self, marker_id, lat, lng):
        """Save a marker to the database"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            marker_id_str = str(marker_id)
            
            query = "INSERT INTO markers (id, timestamp, lat, lng) VALUES (%s, %s, %s, %s)"
            params = (marker_id_str, timestamp, lat, lng)
            
            rows_affected = self.execute_update(query, params)
            return rows_affected > 0
        except Exception as e:
            print(f"Error saving marker {marker_id}: {e}")
            return False

    def delete_marker(self, marker_id):
        """Delete a marker from the database"""
        try:
            marker_id_str = str(marker_id)
            query = "DELETE FROM markers WHERE id = %s"
            params = [marker_id_str]
            rows_affected = self.execute_update(query, params)
            return rows_affected > 0
        except Exception as e:
            print(f"Error deleting marker {marker_id}: {e}")
            return False

    def get_next_marker_id(self):
        """Get the next available marker ID"""
        try:
            query = "SELECT id FROM markers"
            results = self.execute_query(query)
            
            numeric_ids = []
            for row in results:
                try:
                    numeric_ids.append(int(row['id']))
                except (ValueError, TypeError, KeyError):
                    pass
                    
            return max(numeric_ids, default=0) + 1
        except Exception as e:
            print(f"Error getting next marker ID: {e}")
            return 1

    def delete_all_markers(self):
        """Delete all markers from the database"""
        try:
            query = "DELETE FROM markers"
            rows_affected = self.execute_update(query)
            print(f"Deleted {rows_affected} markers.")
            return True
        except Exception as e:
            print(f"Error deleting all markers: {e}")
            return False

    def save_polygon(self, polygon_id, name, coordinates):
        """Save a polygon to the database"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            polygon_id_str = str(polygon_id)
            name_str = str(name)
            
            if not isinstance(coordinates, str): 
                coordinates_str = json.dumps(coordinates)
            else: 
                coordinates_str = coordinates
                
            query = "INSERT INTO polygons (polygon_id, timestamp, name, coordinates) VALUES (%s, %s, %s, %s)"
            params = (polygon_id_str, timestamp, name_str, coordinates_str)
            
            rows_affected = self.execute_update(query, params)
            return rows_affected > 0
        except Exception as e:
            print(f"Error saving polygon {polygon_id_str}: {e}")
            return False

    def update_polygon_name(self, polygon_id, new_name):
        """Update polygon name"""
        try:
            polygon_id_str = str(polygon_id)
            new_name_str = str(new_name)
            
            query = "UPDATE polygons SET name = %s WHERE polygon_id = %s"
            params = (new_name_str, polygon_id_str)
            
            rows_affected = self.execute_update(query, params)
            return rows_affected > 0
        except Exception as e:
            print(f"Error updating polygon name for {polygon_id}: {e}")
            return False

    def delete_polygon(self, polygon_id):
        """Delete a polygon from the database"""
        try:
            polygon_id_str = str(polygon_id)
            query = "DELETE FROM polygons WHERE polygon_id = %s"
            params = [polygon_id_str]
            rows_affected = self.execute_update(query, params)
            return rows_affected > 0
        except Exception as e:
            print(f"Error deleting polygon {polygon_id}: {e}")
            return False

    def delete_all_polygons(self):
        """Delete all polygons from the database"""
        try:
            query = "DELETE FROM polygons"
            rows_affected = self.execute_update(query)
            print(f"Deleted {rows_affected} polygons.")
            return True
        except Exception as e:
            print(f"Error deleting all polygons: {e}")
            return False

    def get_next_polygon_id(self):
        """Get the next available polygon ID"""
        try:
            query = "SELECT polygon_id FROM polygons"
            results = self.execute_query(query)
            
            numeric_ids = []
            for row in results:
                try:
                    if isinstance(row['polygon_id'], str) and row['polygon_id'].startswith('poly-'):
                         numeric_part = row['polygon_id'].split('-')[-1]
                         numeric_ids.append(int(numeric_part))
                except (ValueError, IndexError, TypeError, KeyError):
                    pass
                    
            return max(numeric_ids, default=0) + 1
        except Exception as e:
            print(f"Error getting next polygon ID: {e}")
            return 1

    def get_image_counts_batch(self, device_ids):
        """Batch get image counts from bears_images_unified"""
        try:
            if not device_ids:
                return {}
            
            placeholders = ','.join(['%s'] * len(device_ids))
            query = f"""
                SELECT device_id, image_type, COUNT(*) as count
                FROM bears_images_unified
                WHERE device_id IN ({placeholders})
                AND parsed_successfully = 1
                GROUP BY device_id, image_type
            """
            
            results = self.execute_query(query, device_ids)
            
            # Format: {device_id: {'device': count, 'trail': count}}
            counts = {}
            for row in results:
                dev_id = row['device_id']
                img_type = row['image_type']
                count = row['count']
                
                if dev_id not in counts:
                    counts[dev_id] = {'device': 0, 'trail': 0}
                counts[dev_id][img_type] = count
            
            # Fill in zeros for devices without images
            for dev_id in device_ids:
                if dev_id not in counts:
                    counts[dev_id] = {'device': 0, 'trail': 0}
            
            return counts

        except Exception as e:
            print(f"Error in get_image_counts_batch: {e}")
            return {}

    def get_image_count(self, device_id, image_type=None, include_unsuccessful=False):
        """Get image count from bears_images_unified"""
        try:
            query = "SELECT COUNT(*) FROM bears_images_unified WHERE device_id = %s"
            params = [str(device_id)]

            if image_type:
                query += " AND image_type = %s"
                params.append(image_type)

            if not include_unsuccessful:
                query += " AND parsed_successfully = 1"

            count = self.execute_scalar(query, params)
            return count if count else 0

        except Exception as e:
            print(f"Error getting image count: {e}")
            return 0

    def get_images(self, device_id, image_type=None, start_date=None,
                end_date=None, daily_time_filter=None,
                include_unsuccessful=False, limit=100, offset=0):
        """Get images from bears_images_unified table"""
        try:
            query = "SELECT * FROM bears_images_unified WHERE device_id = %s"
            params = [str(device_id)]

            if image_type:
                query += " AND image_type = %s"
                params.append(image_type)

            if not include_unsuccessful:
                query += " AND parsed_successfully = 1"

            if start_date and end_date:
                query += " AND timestamp >= %s AND timestamp <= %s"
                params.extend([start_date, end_date])

            query += " ORDER BY timestamp DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            results = self.execute_query(query, params)
            df = pd.DataFrame(results) if results else pd.DataFrame()

            return df

        except Exception as e:
            print(f"Error executing get_images query: {e}")
            return pd.DataFrame()

    def get_seasonal_data(self, bear_id=None):
        """Get seasonal movement data for bears"""
        try:
            query = """
            SELECT 
                bear_id,
                season,
                sex,
                age,
                COUNT(*) as point_count,
                AVG(x) as avg_x,
                AVG(y) as avg_y,
                MIN(x) as min_x,
                MAX(x) as max_x,
                MIN(y) as min_y,
                MAX(y) as max_y,
                MIN(lat) as min_lat,
                MAX(lat) as max_lat,
                MIN(lng) as min_lng,
                MAX(lng) as max_lng,
                COUNT(DISTINCT date(timestamp)) as day_count
            FROM bears_tracking
            """
            params = []
            
            if bear_id:
                query += " WHERE bear_id = %s AND bear_id IS NOT NULL"
                params.append(bear_id)
            else:
                query += " WHERE bear_id IS NOT NULL"
                
            query += " GROUP BY bear_id, season, sex, age ORDER BY bear_id, season"
            
            results = self.execute_query(query, params)
            df = pd.DataFrame(results) if results else pd.DataFrame()
            return df
        except Exception as e:
            print(f"!!! Error getting seasonal data: {e}")
            return pd.DataFrame()

    def get_home_range_data(self, bear_id=None):
        """Get home range data for bears"""
        try:
            query = """
            SELECT 
                m.bear_id,
                m.sex,
                m.age,
                m.area as mcp_area,
                c.area as core_area,
                k.area as kde_area,
                m.stage
            FROM 
                bears_mcp m
            LEFT JOIN 
                bears_core_area c ON m.bear_id = c.bear_id
            LEFT JOIN 
                bears_kde k ON m.bear_id = k.bear_id
            """
            params = []
            
            if bear_id:
                query += " WHERE m.bear_id = %s"
                params.append(bear_id)
                
            query += " ORDER BY m.bear_id"
            
            results = self.execute_query(query, params)
            df = pd.DataFrame(results) if results else pd.DataFrame()
            return df
        except Exception as e:
            print(f"!!! Error getting home range data: {e}")
            return pd.DataFrame()

    def get_daily_movement(self, bear_id=None, start_date=None, end_date=None):
        """Get daily movement data for bears"""
        try:
            query = """
            SELECT 
                bear_id,
                date,
                x,
                y,
                lat,
                lng,
                distance,
                season,
                altitude
            FROM bears_daily_displacement
            """
            params = []
            
            where_clauses = []
            if bear_id:
                where_clauses.append("bear_id = %s")
                params.append(bear_id)
                
            if start_date:
                start_iso = start_date.isoformat() if isinstance(start_date, datetime) else start_date
                where_clauses.append("date >= %s")
                params.append(start_iso)
                
            if end_date:
                end_iso = end_date.isoformat() if isinstance(end_date, datetime) else end_date
                where_clauses.append("date <= %s")
                params.append(end_iso)
                
            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)
                
            query += " ORDER BY bear_id, date"
            
            results = self.execute_query(query, params)
            df = pd.DataFrame(results) if results else pd.DataFrame()
            
            if not df.empty and 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
                
            return df
        except Exception as e:
            print(f"!!! Error getting daily movement data: {e}")
            return pd.DataFrame()

    def get_bear_movement_by_season(self):
        """Get bear movement data aggregated by season (for compatibility)"""
        return self.get_seasonal_data()


# Updated migration function with fast processing and optional limits
def migrate_all_csv_to_mariadb(limit_bear_records=1000):
    """
    FAST migration function with batch processing and optional record limit for testing
    """
    print("=== FAST CSV to MariaDB Migration ===")
    if limit_bear_records:
        print(f"[warning] TESTING MODE: Limited to {limit_bear_records} bear tracking records")
    
    start_time = datetime.now()
    
    # Initialize database
    try:
        db = WildlifeDatabase()
        print("[ok] MariaDB connection established")
    except Exception as e:
        print(f"[error] Error connecting to MariaDB: {e}")
        return False
    
    # Initialize schema
    print("\n[1/6] Initializing database schema...")
    if db.initialize_db():
        print("[ok] Database schema initialized")
    else:
        print("[error] Database schema initialization failed")
        return False
    
    # Import Japan system data
    print("\n[2/6] Fast importing deterrent devices...")
    if db.import_deterrent_devices():
        print("[ok] Deterrent devices imported (fast)")
    else:
        print("[error] Deterrent devices import failed")
    
    print("\n[3/6] Importing markers...")
    if db.import_markers():
        print("[ok] Markers imported")
    else:
        print("[error] Markers import failed")
    
    print("\n[4/6] Importing polygons...")
    if db.import_polygons():
        print("[ok] Polygons imported")
    else:
        print("[error] Polygons import failed")
    
    # Skip image indexing for faster testing
    print("\n[5/6] Skipping image indexing for faster testing...")
    print("[warning] Image indexing skipped for speed (can be run separately)")
    
    # Import Carpathian Bears data with fast processing
    print("\n[6/6] Fast importing bears tracking data...")
    # Load data with limit support
    tracking_files = [
        "data/animal_data/carpathian_bears/1_bears_RO.csv",
        "data/animal_data/carpathian_bears/2_bears_RO_seasons.csv"
    ]
    
    all_data = []
    for file_path in tracking_files:
        if os.path.exists(file_path):
            print(f"Reading {file_path}...")
            try:
                df = pd.read_csv(file_path, dtype={
                    'X': float, 'Y': float, 'Name': str,
                    'Season': str, 'Season2': str, 'Sex': str, 'age': str
                })
                
                # Handle timestamp column
                timestamp_col = None
                for col in ['Timestamp', 'timestamp', 'DateTime', 'Time']:
                    if col in df.columns:
                        timestamp_col = col
                        break
                        
                if timestamp_col:
                    df[timestamp_col] = pd.to_datetime(df[timestamp_col], errors='coerce')
                    df.dropna(subset=[timestamp_col], inplace=True)
                    df.rename(columns={timestamp_col: 'Timestamp'}, inplace=True)
                
                all_data.append(df)
                print(f"Read {len(df)} records")
                
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
                continue
    
    if all_data:
        combined_df = pd.concat(all_data, ignore_index=True)
        print(f"Combined {len(combined_df)} total tracking records")
        
        if db._insert_bears_tracking_data(combined_df, limit_records=limit_bear_records):
            print("[ok] Bears tracking data imported (fast)")
        else:
            print("[error] Bears tracking data import failed")
    else:
        print("[error] No bear tracking data found")
    
    # Verification
    print("\n[FINAL] Verifying migration...")
    try:
        deterrents = db.get_deterrent_devices()
        markers = db.get_markers()
        polygons = db.get_polygons()
        bears = db.get_bears_list()
        
        print(f"[ok] Deterrent devices: {len(deterrents)} records")
        print(f"[ok] Markers: {len(markers)} records")
        print(f"[ok] Polygons: {len(polygons)} records")
        print(f"[ok] Bears: {len(bears)} unique bears")
        
        if not bears.empty:
            tracking_count = db.execute_scalar("SELECT COUNT(*) FROM bears_tracking")
            print(f"[ok] Bear tracking records: {tracking_count}")
        
        print("[ok] Migration verification completed")
        
    except Exception as e:
        print(f"[error] Verification failed: {e}")
    
    end_time = datetime.now()
    elapsed_time = (end_time - start_time).total_seconds()
    
    print(f"\n=== FAST Migration Completed in {elapsed_time:.2f} seconds ===")
    print("Wildlife tracking system is ready.")
    print("You can now run: streamlit run map.py")
    print("\nFor full migration without limits, use:")
    print("migrate_all_csv_to_mariadb(limit_bear_records=None)")
    
    return True


if __name__ == "__main__":

    db = WildlifeDatabase()

    
    db.execute_update("DELETE FROM image_metadata")
    print("Old image metadata deleted.")

    db.index_image_files()

    print("Starting FAST migration with 1000 records for testing...")
    migrate_all_csv_to_mariadb(limit_bear_records=None)