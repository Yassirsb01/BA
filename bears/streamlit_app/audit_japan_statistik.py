"""Read-only parameter sensitivity audit for the Japanese camera timing statistic.

Place this file next to activity_overlap.py inside bears/streamlit_app.

    python audit_japan_statistik.py --runs 60    # preliminary
    python audit_japan_statistik.py --runs 300   # documented full configuration
    python audit_japan_statistik.py --runs 300 --seed 43  # robustness across seeds

The exact same simulated paths are evaluated under different camera radii;
therefore only the parameter being evaluated changes. No source code, MariaDB
records, or cached terrain data is modified. Outputs an audit CSV locally.

The statistic here uses point-by-point hour samples (as in activity_overlap.py),
not camera-entry events (as in the animated map). Do not compare these counts
as if they were identical events.
"""

from __future__ import annotations

import argparse
import csv
import math
from datetime import datetime
from pathlib import Path

import numpy as np
from geopy.distance import geodesic

import activity_overlap as ao
import japan_comparison as jc
from wildlife_db_mariadb import WildlifeDatabase


RADII_M = (50, 100, 150, 200, 300)
GRID = np.linspace(0, 24, 481)
DX = GRID[1] - GRID[0]


def fast_distance_m(lat1, lng1, lat2, lng2):
    """Conservative coarse filter only: exact geodesic is used near cameras."""
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    lat1r = math.radians(lat1)
    lat2r = math.radians(lat2)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(lat1r) * math.cos(lat2r) * math.sin(d_lng / 2) ** 2)
    return 2 * 6371008.8 * math.asin(min(1.0, math.sqrt(a)))


def nearest_camera_distance(point, camera_positions, threshold=400.0):
    lat, lng = point["lat"], point["lng"]
    close_cameras = [(clat, clng) for clat, clng in camera_positions
                     if fast_distance_m(lat, lng, clat, clng) <= threshold]
    if not close_cameras:
        return math.inf
    return min(geodesic((lat, lng), c).meters for c in close_cameras)


def estimate_delta(real_hours, sim_hours, bandwidth):
    if not real_hours or not sim_hours:
        return None
    a = ao.circular_kde(real_hours, GRID, bandwidth)
    b = ao.circular_kde(sim_hours, GRID, bandwidth)
    a = a / max(float(a.sum() * DX), 1e-12)
    b = b / max(float(b.sum() * DX), 1e-12)
    return ao.overlap_coefficient(a, b, DX)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=60, help="number of 48-hour tracks (60 quick, 300 full)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("japan_statistik_audit.csv"))
    args = parser.parse_args()
    if not (1 <= args.runs <= 2000):
        parser.error("--runs must be between 1 and 2000")

    cameras = jc.load_japan_cameras()
    if not cameras:
        raise RuntimeError("No Japanese cameras available: check 2024Bear/ReadMe.csv")

    db = WildlifeDatabase()
    if not ao.check_db_reachable_bounded(db):
        raise RuntimeError("MariaDB unavailable. Connect university VPN before running this audit.")
    real_hours, n_excluded = ao.get_real_detection_hours(db)
    if not real_hours:
        raise RuntimeError("No real camera detection timestamps found in MariaDB.")

    print(f"Cameras: {len(cameras)}; valid real timestamps: {len(real_hours)}; "
          f"excluded placeholder IDs: {n_excluded}", flush=True)
    print(f"Simulating {args.runs} x 48h (seed={args.seed}) with terrain OFF.", flush=True)
    print("Only one set of paths is simulated. All radii reuse identical paths.", flush=True)

    speed_source = jc.DatabaseConnection(jc.SIM_DB_PATH)
    bear_speeds = jc.BearSpeeds(speed_source)
    rng = np.random.default_rng(args.seed)
    camera_positions = [(c["lat"], c["lng"]) for c in cameras]
    # One item per hour when within 300m of at least one camera:
    # (run_index, step_index, hour_of_day, minimum geodesic distance).
    events = []

    for i in range(args.runs):
        # Draw random inputs in precisely the same sequence as the original
        # activity_overlap.run_monte_carlo_virtual_detections function.
        cam = cameras[int(rng.integers(0, len(cameras)))]
        gender = jc.VALID_GENDERS[int(rng.integers(0, len(jc.VALID_GENDERS)))]
        age = jc.VALID_AGES[int(rng.integers(0, len(jc.VALID_AGES)))]
        season = jc.VALID_SEASONS[int(rng.integers(0, len(jc.VALID_SEASONS)))]
        hour = int(rng.integers(0, 24))
        bear_seed = int(rng.integers(0, 10_000_000))
        path = jc.simulate_free_path(
            start_lat=cam["lat"], start_lng=cam["lng"],
            start_time=datetime(2024, 1, 1, hour, 0, 0),
            duration_hours=48, gender=gender, age=age, season=season,
            bear_speeds=bear_speeds, seed=bear_seed, terrain_cache=None,
        )
        for step_index, point in enumerate(path[1:], start=1):
            d = nearest_camera_distance(point, camera_positions)
            if d <= max(RADII_M):
                t = point["time"]
                events.append((i, step_index, t.hour + t.minute / 60, d))
        if (i + 1) % 25 == 0 or i + 1 == args.runs:
            print(f"  {i + 1}/{args.runs} simulated", flush=True)

    rows = []

    def add(group, radius, runs, hours, bandwidth):
        sample = [e[2] for e in events
                  if e[0] < runs and e[1] <= hours and e[3] <= radius]
        delta = estimate_delta(real_hours, sample, bandwidth)
        rows.append({"group": group, "radius_m": radius, "runs": runs,
                     "hours_per_run": hours, "bandwidth_h": bandwidth,
                     "real_count": len(real_hours), "sim_count": len(sample),
                     "delta": "" if delta is None else f"{delta:.5f}",
                     "seed": args.seed})

    for radius in RADII_M:
        add("radius", radius, args.runs, 48, 1.5)
    for runs in sorted(set([min(50, args.runs), min(150, args.runs), args.runs])):
        add("run_count", 150, runs, 48, 1.5)
    for hours in (24, 48):
        add("duration", 150, args.runs, hours, 1.5)
    for bandwidth in (0.75, 1.0, 1.5, 2.0, 3.0):
        add("bandwidth", 150, args.runs, 48, bandwidth)

    print("\nParameter                  Radius Runs Duration KDE   Sim N   Delta")
    print("-" * 76)
    for row in rows:
        print(f"{row['group']:<27} {row['radius_m']:>3}m "
              f"{row['runs']:>4}  {row['hours_per_run']:>2}h "
              f"{row['bandwidth_h']:>4}h {row['sim_count']:>7}   "
              f"{row['delta'] or 'N/A'}")

    baseline = next((r for r in rows if r["group"] == "radius" and r["radius_m"] == 150), None)
    if args.runs == 300 and args.seed == 42 and baseline:
        print("\nFull reference comparison for current project code:")
        print(f"  expected older run: N_sim=1958, delta about 0.615")
        print(f"  current computed: N_sim={baseline['sim_count']}, delta={baseline['delta']}")
        if baseline["sim_count"] != 1958:
            print("  WARNING: reference count differs; inspect local source/data revisions")
        else:
            print("  Counts match the documented 150m reference run.")

    with args.output.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSaved summary CSV: {args.output.resolve()}")
    print("No database records or application source files were modified.")
    print("NOTE: these are hourly point detections, not camera-entry events.")


if __name__ == "__main__":
    main()
