"""Read-only audit: hourly camera-proximity samples vs. camera-entry events.

Run from bears/streamlit_app, next to activity_overlap.py and audit_japan_statistik.py:

    python .\audit_japan_ereignisse.py --runs 60 --seed 42
    python .\audit_japan_ereignisse.py --runs 300 --seed 42
    python .\audit_japan_ereignisse.py --runs 300 --seed 43

No modifications to application code, MariaDB, or terrain cache.

IMPORTANT:
- A point detection means an hourly simulated GPS position lies within a
  camera's assumed radius (the current activity_overlap.py definition).
- A camera-entry event means a camera changes from 'outside' to 'inside'
  between hourly samples, with the initial camera(s) already occupied at t=0.
- The map animation interpolates between hourly GPS positions, so these
  hourly entry events are NOT yet a pixel-perfect match for the map events.
- They are diagnostics, not actual observed photographs or independent
  detections of known animals.
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


def haversine_m(lat1, lng1, lat2, lng2):
    la1, la2 = math.radians(lat1), math.radians(lat2)
    dl = la2 - la1
    dg = math.radians(lng2 - lng1)
    a = math.sin(dl/2)**2 + math.cos(la1)*math.cos(la2)*math.sin(dg/2)**2
    return 2*6371008.8*math.asin(min(1., math.sqrt(max(0., a))))


def nearby_camera_distances(pt, cams):
    """Exact geodesic only for candidates potentially within 300 metres."""
    close = []
    for i, (lat, lng) in enumerate(cams):
        if haversine_m(pt['lat'], pt['lng'], lat, lng) < 310.0:
            d = geodesic((pt['lat'], pt['lng']), (lat, lng)).meters
            if d <= max(RADII_M):
                close.append((i, d))
    return close


def delta(real_hours, sim_hours, bandwidth=1.5):
    if not real_hours or not sim_hours:
        return None
    a = ao.circular_kde(real_hours, GRID, bandwidth)
    b = ao.circular_kde(sim_hours, GRID, bandwidth)
    a /= max(float(a.sum()*DX), 1e-12)
    b /= max(float(b.sum()*DX), 1e-12)
    return ao.overlap_coefficient(a, b, DX)


def classify_path(path, cameras, radii):
    """Return exactly one diagnostic record for each radius.

    This function uses hourly samples and checks entry transitions per camera.
    Step zero initializes camera occupancy; it is not a detection event.
    """
    cams = [(c['lat'], c['lng']) for c in cameras]
    indexed_dists = [nearby_camera_distances(p, cams) for p in path]
    out = {}
    for r in radii:
        active0 = {idx for idx,d in indexed_dists[0] if d<=r}
        active_prev = active0
        point_times = []
        entry_times = []
        entry_camera_events = 0
        points_first_six = 0
        points_first_24 = 0
        points_last_24 = 0
        points_other_cameras = 0
        entries_other_cameras = 0
        for step, p in enumerate(path[1:],1):
            active = {idx for idx,d in indexed_dists[step] if d<=r}
            if active:
                t = p['time']
                hour = t.hour + t.minute/60
                point_times.append(hour)
                if step <= 6: points_first_six += 1
                if step <= 24: points_first_24 += 1
                else: points_last_24 += 1
                if len(active - active0):
                    points_other_cameras += 1
            new = active - active_prev
            if new:
                entry_times.append(p['time'].hour + p['time'].minute / 60)
                entry_camera_events += len(new)
                entries_other_cameras += len(new - active0)
            active_prev = active
        out[r] = dict(point_times=point_times, entry_times=entry_times,
                      per_camera_entry_events=entry_camera_events,
                      points_other_cameras=points_other_cameras,
                      points_first_six=points_first_six,
                      points_first_24=points_first_24,
                      points_last_24=points_last_24,
                      entries_other_cameras=entries_other_cameras)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runs', type=int, default=60)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--output', type=Path, default=None)
    a = p.parse_args()
    if not 1<=a.runs<=1500: p.error('Expected --runs 1 to 1500')
    output = a.output or Path(f'japan_ereignisse_seed{a.seed}_{a.runs}.csv')
    cameras = jc.load_japan_cameras()
    if not cameras: raise RuntimeError('No Japanese camera coordinates found')
    db = WildlifeDatabase()
    if not ao.check_db_reachable_bounded(db):
        raise RuntimeError('MariaDB unreachable; turn on university VPN')
    real, excluded = ao.get_real_detection_hours(db)
    if not real: raise RuntimeError('No real detection timestamps available')
    print(f'Cameras: {len(cameras)}; real timestamps: {len(real)}; excluded: {excluded}')
    print(f'Simulating {a.runs} x 48h, seed {a.seed}, terrain OFF; initial camera presence is NOT a new entry.',flush=True)

    speed = jc.BearSpeeds(jc.DatabaseConnection(jc.SIM_DB_PATH))
    rng = np.random.default_rng(a.seed)
    acc = {r: dict(point=[], entry=[], n_entry_cameras=0, other_camera_point=0,
                   other_camera_entry=0, first_six=0, first_24=0, last_24=0,
                   paths_with_entry=0) for r in RADII_M}
    for run in range(a.runs):
        start = cameras[int(rng.integers(0,len(cameras)))]
        gender = jc.VALID_GENDERS[int(rng.integers(0,len(jc.VALID_GENDERS)))]
        age = jc.VALID_AGES[int(rng.integers(0,len(jc.VALID_AGES)))]
        season = jc.VALID_SEASONS[int(rng.integers(0,len(jc.VALID_SEASONS)))]
        hour = int(rng.integers(0,24))
        path_seed = int(rng.integers(0,10_000_000))
        path = jc.simulate_free_path(start_lat=start['lat'],start_lng=start['lng'],
                    start_time=datetime(2024,1,1,hour,0,0),duration_hours=48,
                    gender=gender,age=age,season=season,bear_speeds=speed,
                    seed=path_seed,terrain_cache=None)
        # Compute camera distances only once per path, all radii reuse them.
        by_r = classify_path(path,cameras,RADII_M)
        for radius,values in by_r.items():
            x=acc[radius]
            x['point'].extend(values['point_times'])
            x['entry'].extend(values['entry_times'])
            x['n_entry_cameras'] += values['per_camera_entry_events']
            x['other_camera_point'] += values['points_other_cameras']
            x['other_camera_entry'] += values['entries_other_cameras']
            x['first_six'] += values['points_first_six']
            x['first_24'] += values['points_first_24']
            x['last_24'] += values['points_last_24']
            x['paths_with_entry'] += int(bool(values['entry_times']))
        if (run+1)%25==0 or run+1==a.runs:
            print(f'  {run+1}/{a.runs} simulated',flush=True)

    rows=[]
    print('\nRadius  Point N  Entry N  Entry/cam  Runs w/ entry  Delta point  Delta entry  First 6h  First 24h  After 24h')
    print('-'*119)
    for radius,x in acc.items():
        dp=delta(real,x['point']);de=delta(real,x['entry'])
        row=dict(radius_m=radius,sim_runs=a.runs,seed=a.seed,real_n=len(real),
                 point_n=len(x['point']),entry_n=len(x['entry']),
                 entry_camera_events=x['n_entry_cameras'],
                 runs_with_entry=x['paths_with_entry'],
                 delta_points='' if dp is None else f'{dp:.5f}',
                 delta_entries='' if de is None else f'{de:.5f}',
                 point_n_first_6h=x['first_six'],point_n_first_24h=x['first_24'],
                 point_n_after_24h=x['last_24'],
                 point_n_near_noninitial_camera=x['other_camera_point'],
                 entry_n_to_noninitial_camera=x['other_camera_entry'])
        rows.append(row)
        print(f'{radius:>4}m  {len(x["point"]):>7}  {len(x["entry"]):>7}  '
              f'{x["n_entry_cameras"]:>9}  {x["paths_with_entry"]:>13}  '
              f'{f"{dp:.5f}" if dp is not None else "N/A":>11}  '
              f'{f"{de:.5f}" if de is not None else "N/A":>11}  '
              f'{x["first_six"]:>8}  {x["first_24"]:>9}  {x["last_24"]:>9}')
    reference=(1958 if a.seed==42 else 1798) if a.runs==300 and a.seed in (42,43) else None
    if reference is not None:
        actual=len(acc[150]['point'])
        print(f'\n150m baseline: expected {reference}, got {actual}: '
              + ('PASS' if actual==reference else 'MISMATCH — check code revisions!'))
    print('\nDiagnostics at 150m:')
    x=acc[150]
    print(f'  Hourly samples close to a camera: {len(x["point"])}')
    print(f'  Of these, hours 1–6: {x["first_six"]}')
    print(f'  Of these, hours 1–24: {x["first_24"]}')
    print(f'  Of these, hours 25–48: {x["last_24"]}')
    print(f'  Hours near any camera not already within radius at start: {x["other_camera_point"]}')
    print(f'  Hourly newly entered camera-region events (max 1 per hour): {len(x["entry"])}')
    print(f'  Individual new camera regions entered: {x["n_entry_cameras"]}')
    print(f'  Paths with at least one new camera-region entry: {x["paths_with_entry"]}/{a.runs}')
    print(f'  New entries to camera regions not active at start: {x["other_camera_entry"]}')

    with output.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print(f'\nSaved: {output.resolve()}')
    print('No application code, MariaDB records, or terrain cache were changed.')
    print('Reminder: interpolated browser-animation event timing can differ from hourly sampled entry events.')

if __name__=='__main__': main()
