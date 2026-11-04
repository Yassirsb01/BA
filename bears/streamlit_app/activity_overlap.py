"""
activity_overlap.py
=====================
Compares the DAILY ACTIVITY pattern of real Japanese camera triggers with
that of a simulated bear (the movement model of Fabian Breu, transferred to
the Japanese camera landscape), reduced to a single figure: the overlap
coefficient Delta, where 0 means no agreement and 1 means identical.

Why the data is pooled rather than analysed per camera: the real data holds
only 36 to 52 timestamps spread over 8 to 20 cameras, which is far too thin
for a distribution PER camera. Pooled over all cameras the sample is large
enough for a kernel density estimate, which still has to be interpreted
with caution.

Method:
  - Real detections: times of day from bears_images_unified, excluding the
    placeholder device IDs (199999, 999999), which most likely come from
    failed ID detection during the e-mail import.
  - Simulated detections: many Monte Carlo runs rather than the single run
    in japan_comparison.py. Each run places a virtual bear at a random
    camera location with random sex, age and season, in order to average
    over the unknown demography, and moves it according to the model.
    Whenever it comes within DETECTION_RADIUS_M of a camera, that counts
    as a virtual trigger and its time of day is recorded.
  - Both distributions of times are smoothed by circular density
    estimation (a wrapped Gaussian KDE, so that 23:00 and 00:00 are
    correctly treated as close together rather than at opposite ends of a
    line) and compared through the overlap coefficient
    Delta = integral(min(f1, f2)). This is the standard measure in the
    camera trap literature (Ridout and Linkie, 2009), rebuilt here on the
    same principle but without the von Mises kernel of the R "overlap"
    package.
  - Uncertainty: bootstrap resampling with replacement from both samples,
    recomputing Delta 1000 times, which yields a 95 % confidence interval
    instead of a single figure that would look unjustifiably precise.
"""

import os
import sys
from datetime import datetime

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Reuse the building blocks already implemented and tested in
# japan_comparison.py (camera list, path simulation, database check)
# instead of duplicating the logic.
from japan_comparison import (  # noqa: E402
    load_japan_cameras, simulate_free_path,
    DatabaseConnection, BearSpeeds, SIM_DB_PATH,
    VALID_GENDERS, VALID_AGES, VALID_SEASONS,
)
from geopy.distance import geodesic  # noqa: E402
from wildlife_db_mariadb import WildlifeDatabase  # noqa: E402

import threading  # noqa: E402


def check_db_reachable_bounded(db: "WildlifeDatabase", timeout_sec: float = 6.0) -> bool:
    """
    Like check_db_reachable() in japan_comparison.py, but with a HARD time
    limit enforced through a background thread, which works on every
    platform including Windows, unlike signal.alarm().

    Rationale: WildlifeDatabase does not set an explicit connection_timeout
    for mysql.connector. If a network silently drops packets instead of
    actively refusing the connection, the attempt can otherwise hang for
    minutes before any error surfaces, which is unacceptable for an
    interactive analysis script.
    """
    result = {"ok": False}

    def _try_connect():
        try:
            conn = db._get_connection()
            conn.close()
            result["ok"] = True
        except Exception:
            result["ok"] = False

    t = threading.Thread(target=_try_connect, daemon=True)
    t.start()
    t.join(timeout_sec)
    if t.is_alive():
        # The attempt is still running after the deadline, so treat the
        # database as unreachable. The thread is a daemon and may linger in
        # the background, but it no longer blocks the script.
        return False
    return result["ok"]

# Device IDs identified as placeholders or error values during the data
# check; they do not follow the pattern of the real six-digit IDs.
PLACEHOLDER_DEVICE_IDS = {"199999", "999999"}

DETECTION_RADIUS_M = 100  # camera detection radius, as in japan_comparison.py


# =========================================================
# 1) Real detection times from the database
# =========================================================
def get_real_detection_hours(db: "WildlifeDatabase", exclude_ids=PLACEHOLDER_DEVICE_IDS):
    """
    Read all timestamps from bears_images_unified, which combines the file
    system and e-mail sources and is more complete than image_metadata
    alone, and convert them to decimal hours (19:30 becomes 19.5).

    Returns:
        (hours: list[float], n_excluded: int)
    """
    rows = db.execute_query(
        "SELECT device_id, timestamp FROM bears_images_unified WHERE timestamp IS NOT NULL"
    )
    hours = []
    n_excluded = 0
    for r in rows or []:
        device_id = str(r.get("device_id"))
        if device_id in exclude_ids:
            n_excluded += 1
            continue
        ts = r.get("timestamp")
        try:
            dt = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
        except (ValueError, TypeError):
            continue
        hours.append(dt.hour + dt.minute / 60.0)
    return hours, n_excluded


#--------------------------- Hilfefunktion 17.10.2026


def get_camera_entry_events(path, cameras, detection_radius_m):
    """
    Count a new entry for each camera whose assumed
    detection area is entered.

    Initial camera occupancy at t=0 is not counted.
    Consecutive positions inside the same camera area
    do not create repeated events.

    Positions are sampled hourly. This does not
    reproduce the interpolated timing of the map.
    """
    if not path:
        return []

    def cameras_in_range(point):
        pos = (point["lat"], point["lng"])
        return [
            cam for cam in cameras
            if geodesic(
                pos, (cam["lat"], cam["lng"])
            ).meters <= detection_radius_m
        ]

    # The bear starts at a camera. That is not an arrival.
    initial_cameras = cameras_in_range(path[0])
    previous_ids = {
        cam["device_id"] for cam in initial_cameras
    }

    events = []

    for point in path[1:]:
        nearby = cameras_in_range(point)
        current_ids = {
            cam["device_id"] for cam in nearby
        }

        # Only cameras newly entered in this time step.
        new_cameras = [
            cam for cam in nearby
            if cam["device_id"] not in previous_ids
        ]

        for cam in new_cameras:
            events.append({
                "time": point["time"],
                "lat": point["lat"],
                "lng": point["lng"],
                "camera_id": cam["device_id"],
                "camera_lat": cam["lat"],
                "camera_lng": cam["lng"],
            })

        previous_ids = current_ids

    return events
#Wenn ein Bär mehrere Stunden in demselben Kamerabereich bleibt, entsteht nur ein Eintritt. Verlässt er den Bereich und kommt später zurück, zählt das erneut.

# =========================================================
# 2) Monte Carlo simulation: virtual camera triggers
# =========================================================
def run_monte_carlo_virtual_detections(
    n_runs: int = 300,
    hours_per_run: int = 48,
    detection_radius_m: float = DETECTION_RADIUS_M,
    seed: int = 42,
    terrain_cache=None,
    capture_run: bool = False,
) -> tuple[list[float], dict | None]:
    """
    Simulate n_runs independent bear paths, each hours_per_run hours long,
    from random camera locations with random sex, age and season. The
    randomisation averages over the unknown demography of the Japanese
    population, since it is not known which animal triggered which camera.
    Every approach within detection_radius_m of ANY camera counts as a
    virtual trigger and its time of day is collected.

    The starting point itself is by definition a camera and is NOT counted,
    as otherwise every run would trivially be "detected immediately".

    Args:
        capture_run: if True, ONE complete run (path plus detection events)
            is returned as well, for an animation in the user interface.
            Deliberately NOT the run with the most hits, which would be
            cherry-picking for a nicer demonstration, but simply the FIRST
            run with at least one detection. Only the first 15 runs are
            searched, so that the animation does not happen to show a
            completely empty run that looks like a failure. The interface
            labels it as one random run rather than a best case.

    Returns:
        (virtual_hours, captured_run). captured_run is None if
        capture_run=False or if none of the first 15 runs had a hit.
        Otherwise it is a dict:
          {"path": [...], "detections": [{"time": datetime, "lat", "lng",
           "camera_id"}], "start_camera": {...}}
    """
    cameras = load_japan_cameras()
    if not cameras:
        raise RuntimeError("No Japanese camera locations found. They come from MariaDB (deterrent_devices), so the university VPN has to be active.")

    dbcon = DatabaseConnection(SIM_DB_PATH)
    bear_speeds = BearSpeeds(dbcon)
    rng = np.random.default_rng(seed)

    virtual_hours: list[float] = []
    captured_run: dict | None = None
    capture_search_budget = 15  # only consider the first N runs, see docstring

    for run_idx in range(n_runs):
        start_cam = cameras[rng.integers(0, len(cameras))]
        gender = VALID_GENDERS[rng.integers(0, len(VALID_GENDERS))]
        age = VALID_AGES[rng.integers(0, len(VALID_AGES))]
        season = VALID_SEASONS[rng.integers(0, len(VALID_SEASONS))]
        start_hour = int(rng.integers(0, 24))  # uniform start over the day, no bias
        start_time = datetime(2024, 1, 1, start_hour, 0, 0)

        path = simulate_free_path(
            start_lat=start_cam["lat"], start_lng=start_cam["lng"],
            start_time=start_time, duration_hours=hours_per_run,
            gender=gender, age=age, season=season,
            bear_speeds=bear_speeds, seed=int(rng.integers(0, 10_000_000)),
            terrain_cache=terrain_cache,
        )

        
        run_detections = get_camera_entry_events(
            path, cameras, detection_radius_m
        )

        for event in run_detections:
            t = event["time"]
            virtual_hours.append(
                t.hour + t.minute / 60.0
            )

#    17.10.2026 : A virtual event is counted when a simulated bear
#    newly enters a camera area between hourly samples.
#    The initial occupancy at the starting camera is
#    excluded. Separate cameras are counted separately.
        if capture_run and captured_run is None and run_idx < capture_search_budget:
            if run_detections:
                captured_run = {"path": path, "detections": run_detections, "start_camera": start_cam}
            elif run_idx == capture_search_budget - 1:
                # None of the first 15 runs produced a detection. Showing
                # the last of them, empty, is better than showing nothing;
                # the interface can label it as "no hit in this example".
                captured_run = {"path": path, "detections": [], "start_camera": start_cam}

    return virtual_hours, captured_run


# =========================================================
# 3) Circular density estimation and overlap coefficient
# =========================================================
def circular_kde(hours, grid: np.ndarray, bandwidth: float = 1.5) -> np.ndarray:
    """
    Wrapped Gaussian KDE on the 24 h circle. The data is additionally
    mirrored by -24 h and +24 h, so that 23:30 and 00:30 are correctly
    treated as close together rather than at opposite ends of a line.
    bandwidth is given in hours.
    """
    hours = np.asarray(hours, dtype=float)
    if len(hours) == 0:
        return np.zeros_like(grid)
    extended = np.concatenate([hours - 24, hours, hours + 24])
    diffs = grid[:, None] - extended[None, :]
    weights = np.exp(-0.5 * (diffs / bandwidth) ** 2)
    density = weights.sum(axis=1) / (len(hours) * bandwidth * np.sqrt(2 * np.pi))
    return density


def overlap_coefficient(f1: np.ndarray, f2: np.ndarray, dx: float) -> float:
    """Delta = integral(min(f1, f2)), the standard measure of distribution
    overlap (Ridout and Linkie, 2009), approximated numerically on a grid."""
    return float(np.sum(np.minimum(f1, f2)) * dx)


def bootstrap_delta_ci(
    real_hours, sim_hours, grid: np.ndarray, bandwidth: float,
    n_boot: int = 1000, seed: int = 42, return_samples: bool = False,
):
    """Bootstrap confidence interval for Delta (2.5 %, median, 97.5 %).

    return_samples=True additionally returns all n_boot Delta values, for a
    histogram in the user interface. The default (False) keeps the previous
    behaviour."""
    rng = np.random.default_rng(seed)
    real_hours = np.asarray(real_hours, dtype=float)
    sim_hours = np.asarray(sim_hours, dtype=float)
    dx = grid[1] - grid[0]

    deltas = np.empty(n_boot)
    for i in range(n_boot):
        r = rng.choice(real_hours, size=len(real_hours), replace=True)
        s = rng.choice(sim_hours, size=len(sim_hours), replace=True)
        f1 = circular_kde(r, grid, bandwidth)
        f2 = circular_kde(s, grid, bandwidth)
        f1 = f1 / max(f1.sum() * dx, 1e-12)
        f2 = f2 / max(f2.sum() * dx, 1e-12)
        deltas[i] = overlap_coefficient(f1, f2, dx)

    lo, med, hi = np.percentile(deltas, [2.5, 50, 97.5])
    if return_samples:
        return float(lo), float(med), float(hi), deltas
    return float(lo), float(med), float(hi)


# =========================================================
# 4) Figures, shared by the console script AND the Streamlit page, so that
#    there is only one implementation and the two cannot diverge
# =========================================================
def build_activity_overlap_figure(grid, f_real, f_sim, delta, ci_low, ci_high, n_real, n_sim):
    """Build the comparison figure as a matplotlib figure. It is NOT saved
    here; the caller decides, writing a file from the script or passing it
    to st.pyplot() from the Streamlit page."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.axvspan(18, 24, color="black", alpha=0.05, label="Night (18:00-06:00)")
    ax.axvspan(0, 6, color="black", alpha=0.05)
    ax.plot(grid, f_real, color="#1d6fb8", lw=2.2, label=f"Real detections (Japan, n={n_real})")
    ax.plot(grid, f_sim, color="#e8830c", lw=2.2, label=f"Simulated bear (Carpathian model, n={n_sim})")
    ax.fill_between(grid, np.minimum(f_real, f_sim), color="#6b6b6b", alpha=0.35,
                     label=f"Overlap (delta={delta:.2f})")
    ax.set_xlim(0, 24)
    ax.set_xticks(range(0, 25, 2))
    ax.set_xlabel("Time of day")
    ax.set_ylabel("Activity density")
    ax.set_title(f"Daily activity comparison: delta = {delta:.2f}  "
                 f"(95 % bootstrap CI [{ci_low:.2f}, {ci_high:.2f}])")
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    return fig


def build_bootstrap_histogram_figure(deltas: np.ndarray, delta_point: float, ci_low: float, ci_high: float):
    """Histogram of the bootstrap Delta values with point estimate and
    confidence band."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.hist(deltas, bins=40, color="#8fb8dd", edgecolor="white")
    ax.axvline(delta_point, color="black", lw=2.2, label=f"delta from the original data = {delta_point:.2f}")
    ax.axvline(ci_low, color="#c0392b", lw=1.8, ls="--", label=f"95 % bounds: [{ci_low:.2f}, {ci_high:.2f}]")
    ax.axvline(ci_high, color="#c0392b", lw=1.8, ls="--")
    ax.axvspan(ci_low, ci_high, color="#c0392b", alpha=0.08)
    ax.set_xlabel("Delta of a single resample")
    ax.set_ylabel(f"Count out of {len(deltas)} resamples")
    ax.set_title("Bootstrap: how much does delta vary under a slightly different sample?")
    ax.legend(fontsize=9)
    fig.tight_layout()
    return fig


def plot_activity_overlap(grid, f_real, f_sim, delta, ci_low, ci_high,
                           n_real, n_sim, out_path="activity_overlap.png"):
    """Thin wrapper around build_activity_overlap_figure() for command line
    use, which additionally writes the figure to a file."""
    import matplotlib.pyplot as plt
    fig = build_activity_overlap_figure(grid, f_real, f_sim, delta, ci_low, ci_high, n_real, n_sim)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


# =========================================================
# 5) Complete run
# =========================================================
def run_full_analysis(
    n_runs: int = 300,
    hours_per_run: int = 48,
    detection_radius_m: float = DETECTION_RADIUS_M,
    bandwidth: float = 1.5,
    n_boot: int = 1000,
    use_terrain: bool = False,
    seed: int = 42,
    out_path: str = "activity_overlap.png",
) -> dict | None:
    print("=" * 70)
    print("Daily activity comparison: real Japanese detections vs. simulated bear")
    print("=" * 70)

    print(f"Starting Monte Carlo simulation: {n_runs} runs x {hours_per_run} h "
          f"(detection radius {detection_radius_m} m)...")
    result = compute_comparison(
        n_runs=n_runs, hours_per_run=hours_per_run, detection_radius_m=detection_radius_m,
        bandwidth=bandwidth, n_boot=n_boot, use_terrain=use_terrain, seed=seed,
    )

    if not result["db_ok"]:
        print("[note] MariaDB not reachable (is the VPN active?). Only the "
              "simulated side is computed; no comparison is possible.")
    else:
        print(f"Real detections: {result['n_real']} "
              f"({result['n_excluded']} placeholder device IDs excluded)")
        if result["n_real"] < 20:
            print("[note] Small sample (<20); the result is exploratory only, "
                  "see the bootstrap confidence interval below.")

    print(f"Virtual detections (simulated): {result['n_sim']}")
    if not result["n_sim"]:
        print("No virtual detections generated; increase the radius or use more runs or hours.")
        return None
    if not result["n_real"]:
        print("\nNo comparison possible without real data (see the note above).")
        return result

    print(f"\nOverlap coefficient delta = {result['delta']:.3f}")
    print(f"95 % bootstrap confidence interval: [{result['ci_low']:.3f}, {result['ci_high']:.3f}]")

    saved_to = plot_activity_overlap(
        result["grid"], result["f_real"], result["f_sim"], result["delta"],
        result["ci_low"], result["ci_high"],
        n_real=result["n_real"], n_sim=result["n_sim"], out_path=out_path,
    )
    print(f"\nFigure written to: {saved_to}")
    result["plot_path"] = saved_to
    return result


def compute_comparison(
    n_runs: int = 300,
    hours_per_run: int = 48,
    detection_radius_m: float = DETECTION_RADIUS_M,
    bandwidth: float = 1.5,
    n_boot: int = 1000,
    use_terrain: bool = False,
    seed: int = 42,
    capture_run: bool = False,
) -> dict:
    """
    The single place where the complete computation happens, used both by
    the console script (run_full_analysis) and by the Streamlit page, so
    that there can never be two implementations whose results diverge.

    Does NOT raise when the database is unavailable. It reports this
    through result["db_ok"] = False and result["delta"] = None.

    Note that nothing at all can be computed without the database any
    more: the camera locations come from MariaDB too, so neither the real
    photo times nor the simulation are available. Before the locations
    moved out of 2024Bear/ReadMe.csv the simulation could still run on its
    own.
    """
    db = WildlifeDatabase()
    db_ok = check_db_reachable_bounded(db)
    real_hours, n_excluded = ([], 0)
    if db_ok:
        real_hours, n_excluded = get_real_detection_hours(db)

    terrain_cache = None
    if use_terrain:
        from terrain_cache import TerrainCache
        terrain_cache = TerrainCache()

    try:
        sim_hours, captured_run = run_monte_carlo_virtual_detections(
            n_runs=n_runs, hours_per_run=hours_per_run,
            detection_radius_m=detection_radius_m, seed=seed,
            terrain_cache=terrain_cache, capture_run=capture_run,
        )
    except RuntimeError as e:
        # No camera locations. Since they come from MariaDB the simulation
        # cannot run either, so db_ok is reported as False and the caller
        # shows its "database unreachable" note. Raising here would take
        # down a page that is merely missing one of its panels; see the
        # promise in this function's docstring.
        print(f"[activity_overlap] Simulation not possible: {e}")
        sim_hours, captured_run = [], None
        db_ok = False

    result = {
        "db_ok": db_ok, "n_real": len(real_hours), "n_excluded": n_excluded,
        "n_sim": len(sim_hours), "sim_hours": sim_hours, "real_hours": real_hours,
        "captured_run": captured_run,
        "delta": None, "ci_low": None, "ci_high": None,
        "grid": None, "f_real": None, "f_sim": None, "boot_deltas": None,
    }

    if not sim_hours or not real_hours:
        return result

    grid = np.linspace(0, 24, 481)
    dx = grid[1] - grid[0]
    f_real = circular_kde(real_hours, grid, bandwidth)
    f_sim = circular_kde(sim_hours, grid, bandwidth)
    f_real = f_real / max(f_real.sum() * dx, 1e-12)
    f_sim = f_sim / max(f_sim.sum() * dx, 1e-12)
    delta = overlap_coefficient(f_real, f_sim, dx)
    ci_low, ci_med, ci_high, boot_deltas = bootstrap_delta_ci(
        real_hours, sim_hours, grid, bandwidth, n_boot=n_boot, seed=seed, return_samples=True,
    )

    result.update({
        "delta": delta, "ci_low": ci_low, "ci_high": ci_high,
        "grid": grid, "f_real": f_real, "f_sim": f_sim, "boot_deltas": boot_deltas,
    })
    return result


if __name__ == "__main__":
    # The Windows console defaults to cp1252 and cannot print every
    # character used here. The script used to crash with a
    # UnicodeEncodeError at the result output, AFTER the complete Monte
    # Carlo computation had already run. errors="replace" rather than
    # "strict": a question mark in the text is preferable to a lost run.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    run_full_analysis()