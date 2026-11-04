"""
prefetch_terrain.py
=====================
Downloads the OpenStreetMap terrain data for the ENTIRE area of the
Japanese cameras ONCE and converts it locally into the same grid that
terrain_cache.py uses. Afterwards the terrain weighting of the simulation
runs completely offline.

Rationale: previously the Overpass API was queried live at EVERY
simulation step for EVERY candidate heading, which amounts to thousands
of individual requests across several bears and hours. On an unreliable
network this led to waits of several minutes or to the weighting being
switched off entirely. Now a few large queries are issued once, after
which lookups are local and take milliseconds.

This also improves the data itself. The Overpass "around" filter measures
the distance to the OUTLINE of an area, so a point in the middle of a
large forest, far from its edge, was not recognised as forest. Here it is
additionally checked whether a grid point lies INSIDE an area.

Usage (once, on a connection where Overpass is reachable):

    python tools/prefetch_terrain.py

If Python cannot reach the servers but a browser can:

    python tools/prefetch_terrain.py --print-query    (print the query)
    -> paste it into https://overpass-turbo.eu, run it, then use
       "Export" -> "raw data" to save the JSON, for example terrain.json
    python tools/prefetch_terrain.py --from-file terrain.json

The result is written to bear_simulation/data/terrain_cache.db, which can
simply be copied to another machine.
"""

import os
import sys

# Script lives in a subdirectory; the application modules are one level up.
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

import argparse
import json
import math
import os
import shutil
import sqlite3
import sys
import time

import numpy as np
import requests

from terrain_cache import (
    TerrainCache, DEFAULT_CACHE_DB, DEFAULT_QUERY_ELEMENTS, GRID_SIZE_DEG,
    HEADERS, OVERPASS_URLS,
)

DEFAULT_RADIUS_M = 150      # muss zu query_radius_m in japan_comparison.choose_weighted_direction passen
DEFAULT_BUFFER_KM = 5.0     # buffer around the cameras, covering how far simulated bears can travel
DEFAULT_TILE_DEG = 0.08     # download tile size (~9 km); smaller queries mean fewer timeouts
REQUEST_TIMEOUT_S = 240
M_PER_DEG_LAT = 111_320.0

RAW_DIR = os.path.join(os.path.dirname(DEFAULT_CACHE_DB), "terrain_prefetch_raw")


# =========================================================
# 1) Gebiet bestimmen
# =========================================================
def camera_bbox(buffer_km: float) -> tuple[float, float, float, float]:
    """(sued, west, nord, ost) um alle Kamerastandorte plus Puffer."""
    from japan_comparison import load_japan_cameras
    cams = load_japan_cameras()
    if not cams:
        raise RuntimeError("No Japanese camera locations found. They come from MariaDB (deterrent_devices), so the university VPN has to be active.")
    lats = [c["lat"] for c in cams]
    lons = [c["lng"] for c in cams]
    lat_mid = (min(lats) + max(lats)) / 2
    dlat = buffer_km * 1000 / M_PER_DEG_LAT
    dlon = buffer_km * 1000 / (M_PER_DEG_LAT * math.cos(math.radians(lat_mid)))
    return (min(lats) - dlat, min(lons) - dlon, max(lats) + dlat, max(lons) + dlon)


def build_query(bbox, timeout_s: int = 180) -> str:
    """The same tags as terrain_cache.py (and OSM.py of the movement
    model), but queried by bounding box instead of an around-radius
    around a single point."""
    s, w, n, e = bbox
    q = f"[out:json][timeout:{timeout_s}];\n("
    for element_type, tags in DEFAULT_QUERY_ELEMENTS.items():
        for tag in tags:
            q += f'\n  {element_type}["{tag}"]({s:.6f},{w:.6f},{n:.6f},{e:.6f});'
    q += "\n);\nout body geom;"
    return q


# =========================================================
# 2) Download, tiled and resumable
# =========================================================
def download_tiles(bbox, tile_deg: float, raw_dir: str = RAW_DIR) -> tuple[list[str], list[str]]:
    """
    Split the area into tiles and download each one separately. Tiles
    that are already present are skipped, so an interrupted download can
    simply be restarted and continues where it stopped.
    """
    os.makedirs(raw_dir, exist_ok=True)
    s, w, n, e = bbox
    lat_edges = list(np.arange(s, n, tile_deg)) + [n]
    lon_edges = list(np.arange(w, e, tile_deg)) + [e]
    tiles = [
        (i, j, (lat_edges[i], lon_edges[j], lat_edges[i + 1], lon_edges[j + 1]))
        for i in range(len(lat_edges) - 1) for j in range(len(lon_edges) - 1)
    ]

    done, failed = [], []
    for k, (i, j, tb) in enumerate(tiles, 1):
        path = os.path.join(raw_dir, f"tile_{i}_{j}.json")
        if os.path.exists(path):
            print(f"  Tile {k}/{len(tiles)}: already present, skipped")
            done.append(path)
            continue

        query = build_query(tb)
        ok = False
        for url in OVERPASS_URLS:
            try:
                print(f"  Kachel {k}/{len(tiles)}: lade von {url.split('/')[2]} ...", end=" ", flush=True)
                resp = requests.post(url, data={"data": query}, headers=HEADERS, timeout=REQUEST_TIMEOUT_S)
                if resp.status_code == 200:
                    data = resp.json()
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(data, f)
                    print(f"ok ({len(data.get('elements', []))} Elemente)")
                    done.append(path)
                    ok = True
                    break
                print(f"HTTP {resp.status_code}")
            except Exception as ex:
                print(f"Fehler: {type(ex).__name__}")
            time.sleep(2)
        if not ok:
            failed.append(path)
        time.sleep(2)  # do not overload Overpass
    return done, failed


def load_elements(paths: list[str]) -> list[dict]:
    """Read all raw files and remove duplicates, that is, elements that
    appear on tile boundaries."""
    seen, elements = set(), []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        for el in data.get("elements", []):
            key = (el.get("type"), el.get("id"))
            if key in seen:
                continue
            seen.add(key)
            elements.append(el)
    return elements


# =========================================================
# 3) Lokale Rasterung
# =========================================================
def _min_dist_to_segments(px, py, ax, ay, bx, by) -> np.ndarray:
    """Kleinster Abstand jedes Punktes (px,py) zu einer Polylinie (Segmente a->b), in Metern."""
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    len2 = np.where(len2 == 0, 1e-12, len2)
    out = np.empty(len(px))
    chunk = max(1, 2_000_000 // max(1, len(ax)))  # Speicher begrenzen
    for s in range(0, len(px), chunk):
        X = px[s:s + chunk, None]
        Y = py[s:s + chunk, None]
        t = np.clip(((X - ax) * dx + (Y - ay) * dy) / len2, 0.0, 1.0)
        qx, qy = ax + t * dx, ay + t * dy
        out[s:s + chunk] = np.sqrt((X - qx) ** 2 + (Y - qy) ** 2).min(axis=1)
    return out


def _points_in_polygon(px, py, vx, vy) -> np.ndarray:
    """Ray casting: does the point lie inside the closed polygon?"""
    x1, y1, x2, y2 = vx[:-1], vy[:-1], vx[1:], vy[1:]
    denom = np.where(y2 == y1, 1e-12, y2 - y1)
    out = np.empty(len(px), dtype=bool)
    chunk = max(1, 2_000_000 // max(1, len(x1)))
    for s in range(0, len(px), chunk):
        X = px[s:s + chunk, None]
        Y = py[s:s + chunk, None]
        crosses = ((y1 > Y) != (y2 > Y)) & (X < x1 + (Y - y1) * (x2 - x1) / denom)
        out[s:s + chunk] = (crosses.sum(axis=1) % 2) == 1
    return out


SQLITE_HEADER = b"SQLite format 3\x00"


def ensure_usable_db(db_path: str) -> None:
    """
    Check BEFORE downloading and rasterising whether the target database
    is usable.

    Rationale: if the file is damaged, the run used to fail only at the
    very end while writing, after several minutes of rasterisation that
    were then wasted. A damaged file is not deleted here but moved aside
    with a timestamp, and a fresh database is created.
    """
    if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
        return
    try:
        with open(db_path, "rb") as f:
            header_ok = f.read(16) == SQLITE_HEADER
        if header_ok:
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA quick_check").fetchone()
            conn.close()
            return
    except Exception:
        header_ok = False

    backup = f"{db_path}.beschaedigt-{time.strftime('%Y%m%d-%H%M%S')}"
    os.rename(db_path, backup)
    print(f"[note] The existing file {os.path.basename(db_path)} is not a valid "
          f"SQLite database.")
    print(f"       It was renamed to: {os.path.basename(backup)}")
    print(f"       A new database will be created. The downloaded tiles are "
          f"kept, nothing is fetched again.\n")


def element_flags(el: dict) -> set:
    """
    Features of an OSM element as a set of flags.

    Stores BOTH the plain value ("residential"), for backwards
    compatibility with older caches, AND the tag-qualified key
    ("highway=residential" or "landuse=residential"). Only the qualified
    key distinguishes a residential street from a residential area.
    Without that distinction, 51 % of all grid cells in this rural camera
    region counted as settlement merely because a small road runs
    through them.
    """
    tags = el.get("tags", {}) or {}
    flags = set()
    known = {t for tag_list in DEFAULT_QUERY_ELEMENTS.values() for t in tag_list}
    for tag, value in tags.items():
        if tag in known:
            flags.add(tag)
            flags.add(value)
            flags.add(f"{tag}={value}")
    return flags


def rasterize(elements: list[dict], bbox, grid_size_deg: float = GRID_SIZE_DEG,
              radius_m: int = DEFAULT_RADIUS_M) -> tuple[dict, tuple[int, int, int, int]]:
    """
    For every grid point (the same grid as TerrainCache._grid_key), the
    terrain features within radius_m are determined, in the same 0/1 flag
    format as the live query, so that the scoring in
    japan_comparison.TERRAIN_PREFERENCE stays unchanged.
    """
    g = grid_size_deg
    s, w, n, e = bbox
    i_min, i_max = math.floor(s / g), math.ceil(n / g)
    j_min, j_max = math.floor(w / g), math.ceil(e / g)

    lat0, lon0 = (s + n) / 2, (w + e) / 2
    m_lon = M_PER_DEG_LAT * math.cos(math.radians(lat0))
    r_lat, r_lon = radius_m / M_PER_DEG_LAT, radius_m / m_lon

    cell_flags: dict[tuple[int, int], set] = {}
    n_used = 0

    for idx, el in enumerate(elements, 1):
        flags = element_flags(el)
        if not flags:
            continue

        if el.get("type") == "node" and "lat" in el:
            lats, lons = np.array([el["lat"]]), np.array([el["lon"]])
            closed = False
        elif el.get("type") == "way" and el.get("geometry"):
            geom = [p for p in el["geometry"] if p]
            lats = np.array([p["lat"] for p in geom])
            lons = np.array([p["lon"] for p in geom])
            closed = len(geom) >= 4 and lats[0] == lats[-1] and lons[0] == lons[-1]
        else:
            continue

        ci0 = max(i_min, math.floor((lats.min() - r_lat) / g))
        ci1 = min(i_max, math.ceil((lats.max() + r_lat) / g))
        cj0 = max(j_min, math.floor((lons.min() - r_lon) / g))
        cj1 = min(j_max, math.ceil((lons.max() + r_lon) / g))
        if ci0 > ci1 or cj0 > cj1:
            continue

        ii, jj = np.meshgrid(np.arange(ci0, ci1 + 1), np.arange(cj0, cj1 + 1), indexing="ij")
        ii, jj = ii.ravel(), jj.ravel()
        py = (ii * g - lat0) * M_PER_DEG_LAT
        px = (jj * g - lon0) * m_lon
        vy = (lats - lat0) * M_PER_DEG_LAT
        vx = (lons - lon0) * m_lon

        if len(vx) == 1:
            hit = np.hypot(px - vx[0], py - vy[0]) <= radius_m
        else:
            hit = _min_dist_to_segments(px, py, vx[:-1], vy[:-1], vx[1:], vy[1:]) <= radius_m
        if closed:
            hit |= _points_in_polygon(px, py, vx, vy)

        for k in np.nonzero(hit)[0]:
            cell_flags.setdefault((int(ii[k]), int(jj[k])), set()).update(flags)
        n_used += 1

        if idx % 2000 == 0:
            print(f"  ... {idx}/{len(elements)} Elemente verarbeitet")

    print(f"  {n_used} terrain elements recorded in {len(cell_flags)} grid cells")
    return cell_flags, (i_min, i_max, j_min, j_max)


# =========================================================
# 4) In die bestehende Cache-Datenbank schreiben
# =========================================================
def write_cache(cell_flags: dict, index_range, grid_size_deg: float, radius_m: int,
                db_path: str = DEFAULT_CACHE_DB) -> None:
    """
    Write the grid cells into the cache database ATOMICALLY.

    Rationale: the cache file has already become unusable twice. Writing
    therefore goes into a copy next to the target file first; only once
    that copy passes "PRAGMA quick_check" does os.replace() swap it in as
    a single step. If the process is interrupted before that, by a crash
    or a power loss, the old working file stays untouched and at most the
    new run is lost.

    An already damaged target file is caught by ensure_usable_db(), which
    main() calls before rasterising, so it is not checked again here.
    """
    tmp_path = f"{db_path}.tmp-{os.getpid()}"
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
    # Carry over existing entries so that a partial run does not empty the cache
    if os.path.exists(db_path):
        shutil.copy2(db_path, tmp_path)

    try:
        _write_cache_into(cell_flags, index_range, grid_size_deg, radius_m, tmp_path)

        # Erst pruefen, dann ersetzen
        check = sqlite3.connect(tmp_path)
        ok = check.execute("PRAGMA quick_check").fetchone()[0]
        check.close()
        if ok != "ok":
            raise sqlite3.DatabaseError(f"Newly written file is faulty: {ok}")

        os.replace(tmp_path, db_path)   # atomar, auch unter Windows
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _write_cache_into(cell_flags: dict, index_range, grid_size_deg: float, radius_m: int,
                      db_path: str) -> None:
    """The actual write, always into the temporary file; see write_cache()."""
    TerrainCache(db_path=db_path, grid_size_deg=grid_size_deg)  # creates the tables if needed
    g = grid_size_deg
    now = time.time()
    # Keys exactly as in TerrainCache._grid_key: round(x/g)*g == int*g
    rows = [
        (int(i) * g, int(j) * g, radius_m, json.dumps({k: 1 for k in sorted(flags)}), now)
        for (i, j), flags in cell_flags.items()
    ]
    i_min, i_max, j_min, j_max = index_range
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT OR REPLACE INTO terrain_cache (lat_key, lon_key, radius, features_json, cached_at) "
        "VALUES (?, ?, ?, ?, ?)", rows,
    )
    # Do not record the same area twice on a repeated run
    conn.execute(
        "DELETE FROM prefetch_regions WHERE min_lat_key=? AND min_lon_key=? AND max_lat_key=? "
        "AND max_lon_key=? AND radius=?",
        (i_min * g, j_min * g, i_max * g, j_max * g, radius_m),
    )
    conn.execute(
        "INSERT INTO prefetch_regions (min_lat_key, min_lon_key, max_lat_key, max_lon_key, radius, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (i_min * g, j_min * g, i_max * g, j_max * g, radius_m, now),
    )
    conn.commit()
    conn.close()
    n_cells = (i_max - i_min + 1) * (j_max - j_min + 1)
    print(f"  {len(rows)} cells with terrain features stored "
          f"({n_cells} cells in the area in total; the rest demonstrably "
          f"have no features)")


# =========================================================
# 5) Entry point
# =========================================================
def main():
    ap = argparse.ArgumentParser(description="Pre-load terrain data for the Japan simulation once.")
    ap.add_argument("--buffer-km", type=float, default=DEFAULT_BUFFER_KM)
    ap.add_argument("--tile-deg", type=float, default=DEFAULT_TILE_DEG)
    ap.add_argument("--radius", type=int, default=DEFAULT_RADIUS_M)
    ap.add_argument("--bbox", type=float, nargs=4, metavar=("SOUTH", "WEST", "NORTH", "EAST"),
                    help="Specify the area manually instead of deriving it from the cameras")
    ap.add_argument("--print-query", action="store_true",
                    help="Only print the query for overpass-turbo.eu")
    ap.add_argument("--from-file", nargs="+",
                    help="Use Overpass JSON file(s) saved earlier from a browser")
    ap.add_argument("--db", default=DEFAULT_CACHE_DB)
    args = ap.parse_args()

    bbox = tuple(args.bbox) if args.bbox else camera_bbox(args.buffer_km)
    # Load slightly more than is rasterised, so that features just
    # outside the boundary are still taken into account for edge cells
    pad = args.radius / M_PER_DEG_LAT * 1.5
    load_bbox = (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad)

    print(f"Area: south {bbox[0]:.4f}, west {bbox[1]:.4f}, north {bbox[2]:.4f}, east {bbox[3]:.4f}")

    ensure_usable_db(args.db)  # check early so that no computation time is wasted

    if args.print_query:
        print("\nPaste this query into https://overpass-turbo.eu, run it and save "
              "the result as JSON through 'Export' -> 'raw data':\n")
        print(build_query(load_bbox, timeout_s=300))
        return

    t0 = time.time()
    if args.from_file:
        paths = args.from_file
        print(f"\n[1/3] Using {len(paths)} local file(s)")
    else:
        print(f"\n[1/3] Downloading terrain data (tiles of {args.tile_deg} degrees) ...")
        paths, failed = download_tiles(load_bbox, args.tile_deg)
        if failed:
            print(f"\n{len(failed)} tile(s) could not be downloaded. Simply start again "
                  f"(already downloaded tiles are skipped) or use the browser route "
                  f"(--print-query / --from-file). NOTHING is stored, so that gaps "
                  f"cannot be misread as 'no terrain here'.")
            sys.exit(1)

    elements = load_elements(paths)
    print(f"\n[2/3] Rasterising {len(elements)} elements (grid ~150 m, radius {args.radius} m) ...")
    cell_flags, idx_range = rasterize(elements, bbox, radius_m=args.radius)

    print(f"\n[3/3] Writing to {args.db} ...")
    write_cache(cell_flags, idx_range, GRID_SIZE_DEG, args.radius, db_path=args.db)

    print(f"\nFinished in {time.time() - t0:.0f} s. For this area the simulation now "
          f"uses local data exclusively; no further internet requests are made.")


if __name__ == "__main__":
    main()