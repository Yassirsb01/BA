"""
japan_comparison.py
=====================
Transfer experiment: simulates a bear path starting from a real Japanese
camera location, using the movement model of Fabian Breu with empirical
step lengths taken from the Romanian Carpathian data, and checks whether
the simulated path matches real photo triggers at other Japanese cameras
in time and space.

Known limitations, all deliberate:
  - Species mismatch: the Japanese cameras (Fukushima region, Honshu) lie
    within the range of the Asian black bear (Ursus thibetanus), whereas
    the Carpathian training data comes from the European brown bear
    (Ursus arctos). This is a methodological simplification, not an
    equivalence.
  - A single simulated run per call carries a strong random component. A
    robust statement requires many repetitions in a Monte Carlo fashion
    rather than one path; see activity_overlap.py for the aggregated
    analysis. The single run here is a plausibility check, not a
    validation.

Data sources:
  - Camera locations: MariaDB, table deterrent_devices, the same rows the
    main map draws. Needs the university VPN; there is no file fallback,
    so map and simulation can never show a camera in two places.
  - Speed model: bear_simulation/data/database.db, table bear_speeds,
    source "Carpathians".
  - Real photo timestamps: MariaDB through the existing WildlifeDatabase
    class, which requires the university VPN like the other MariaDB
    components.
"""

import math
import os
import random
import sys
from datetime import datetime, timedelta

# Paths to the original movement simulation code (bear_simulation/...)
_BASE = os.path.join(os.path.dirname(__file__), "bear_simulation")
for _p in (_BASE, os.path.join(_BASE, "model"), os.path.join(_BASE, "data"), os.path.join(_BASE, "util")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from data.DatabaseConnection import DatabaseConnection  # noqa: E402
from data.BearSpeeds import BearSpeeds                   # noqa: E402
from GeoToolBox import GeoToolBox                         # noqa: E402
from geopy.distance import geodesic                       # noqa: E402

from wildlife_db_mariadb import WildlifeDatabase           # noqa: E402
from terrain_cache import TerrainCache                      # noqa: E402

SIM_DB_PATH = os.path.join(_BASE, "data", "database.db")

# Values taken from database.db (bear_speeds), not assumed:
VALID_GENDERS = ("M", "F")
VALID_AGES = ("J", "A")   # Juvenil / Adult
VALID_SEASONS = ("spring", "summer", "autumn", "winter")
SIM_SOURCE = "Carpathians"


def _normalize_device_id(raw_id: str) -> str:
    """
    Same normalisation as format_device_id() in japan_deterrents.py.
    Throughout the project device IDs are stored as a six-digit number
    with leading zeros ("3002.0" in the CSV becomes "003002" in the
    database, matching directory names such as 003002/). Without this
    normalisation the database query never finds a match.
    """
    raw_id = str(raw_id).strip()
    try:
        as_float = float(raw_id)
        if as_float == int(as_float):
            return f"{int(as_float):06d}"
    except ValueError:
        pass
    if raw_id.isdigit() and len(raw_id) < 6:
        return raw_id.zfill(6)
    return raw_id


# Fixed processing order of the cameras.
#
# Why this list exists at all: run_monte_carlo_virtual_detections() picks
# the starting camera of every run with cameras[rng.integers(0, n)], so the
# POSITION of a camera in the list decides where a run begins. A fixed seed
# therefore only reproduces a result as long as the order is stable. A
# database returns rows in whatever order the server chooses unless ORDER BY
# says otherwise, so the order has to be pinned down here.
#
# The order is the one of the original survey document (2024Bear/ReadMe.csv).
# It is kept so that results stay comparable with the runs made before the
# camera locations moved from that file into MariaDB. It carries no meaning
# beyond that.
CAMERA_ORDER = [
    "003002", "003001", "003000", "002007", "002006",
    "002005", "002004", "002001", "002002", "002003",
    "004001", "004000", "001012", "001009", "001003",
    "001011", "001010", "001001", "001000", "001013",
]

# Coordinates this close to Null Island are a missing GPS fix, not a
# position; japan_deterrents.py filters them the same way.
_MIN_VALID_DEGREES = 0.01


def load_japan_cameras(db: "WildlifeDatabase | None" = None) -> list[dict]:
    """
    Load the Japanese camera locations from MariaDB (deterrent_devices).

    Returns the devices that carry a usable GPS fix, ordered by
    CAMERA_ORDER. Devices with lat/lng at 0/0 are left out: 13 of the 33
    rows never received coordinates, and a bear started at Null Island
    would corrupt the statistics.

    Returns an empty list when the database cannot be reached. Callers
    report that to the user; there is deliberately no file fallback, so
    that the map and the simulation can never disagree about where a
    camera stands.
    """
    if db is None:
        db = WildlifeDatabase()

    try:
        rows = db.execute_query(
            "SELECT id, directory_name, lat, lng FROM deterrent_devices")
    except Exception as e:
        print(f"[japan_comparison] Camera locations not retrievable: {e}")
        return []

    by_id = {}
    for row in rows or []:
        raw_id = row.get("directory_name") or row.get("id") or ""
        device_id = _normalize_device_id(raw_id)
        try:
            lat = float(row["lat"])
            lng = float(row["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        if abs(lat) < _MIN_VALID_DEGREES and abs(lng) < _MIN_VALID_DEGREES:
            continue
        by_id[device_id] = {"device_id": device_id, "lat": lat, "lng": lng}

    # Known cameras first, in the fixed order. Anything the database holds
    # on top of that is appended by ID, so a device added later shows up
    # instead of silently disappearing.
    cameras = [by_id.pop(d) for d in CAMERA_ORDER if d in by_id]
    cameras.extend(by_id[d] for d in sorted(by_id))
    return cameras


# Preference weights for terrain-weighted heading selection, keyed by OSM
# tag AND value ("tag=value"). Positive means preferred, negative means
# avoided, absent means neutral (0).
#
# These are hand-set approximations, not coefficients fitted by an
# integrated step selection function. That limitation is stated explicitly
# in the user interface.
#
# Rationale for the tag-qualified keys: purely value-based flags cannot
# distinguish two entirely different things, "landuse=residential" (a
# residential area) and "highway=residential" (a residential street). In
# this rural camera region that caused 51 % of all grid cells to count as
# settlement although most of them only carry a small road through a field
# or a forest. The earlier table also assigned "highway": -3 to EVERY road,
# including forest tracks and footpaths. Since 94 % of cells contain some
# kind of road, practically the whole area scored negative (mean -4.83,
# even forest cells at -2.09) and forest barely stood out.
TERRAIN_PREFERENCE_QUALIFIED = {
    # Deckung / bevorzugter Lebensraum
    "landuse=forest": 3.0, "natural=wood": 3.0, "leisure=nature_reserve": 3.0,
    "natural=scrub": 2.0, "natural=grassland": 1.0, "natural=wetland": 1.0,
    "landuse=meadow": 1.0, "natural=tree_row": 0.5, "landuse=orchard": 0.5,
    # Offenland: wenig Deckung, aber Nahrung -> nur leicht negativ
    "landuse=farmland": -0.5, "landuse=vineyard": 0.0,
    # Menschliche Nutzung (Flaechen)
    "landuse=residential": -3.0, "landuse=commercial": -3.0,
    "landuse=industrial": -3.0, "landuse=military": -4.0,
    "place=city": -3.0, "place=town": -3.0, "place=village": -2.0, "place=suburb": -2.0,
    # Strassen nach Klasse statt pauschal
    "highway=motorway": -4.0, "highway=trunk": -3.5, "highway=primary": -3.0,
    "highway=secondary": -2.0, "highway=tertiary": -1.0, "highway=residential": -1.5,
    "highway=unclassified": -0.5, "highway=service": -0.5,
    "highway=track": 0.0, "highway=path": 0.0, "highway=footway": 0.0,
    "railway=rail": -2.0,
}

# Fallback for older cache databases without tag-qualified keys: the same
# logic as far as it works without tag context. A blanket "highway" entry
# is deliberately absent (see above), and "residential" is ambiguous and
# therefore only weakly negative.
TERRAIN_PREFERENCE = {
    "forest": 3.0, "wood": 3.0, "nature_reserve": 3.0, "scrub": 2.0,
    "grassland": 1.0, "wetland": 1.0, "meadow": 1.0, "tree_row": 0.5,
    "farmland": -0.5,
    "motorway": -4.0, "trunk": -3.5, "primary": -3.0, "secondary": -2.0,
    "tertiary": -1.0, "unclassified": -0.5, "service": -0.5,
    "residential": -1.5, "commercial": -3.0, "industrial": -3.0, "military": -4.0,
    "city": -3.0, "town": -3.0, "village": -2.0, "suburb": -2.0, "railway": -2.0,
}

# How strongly score differences influence heading selection. Selection
# probability is proportional to exp(beta * score), the exponential form
# commonly used in step selection functions. Linear weighting made the
# difference between forest and settlement only a factor of about 2 to 3,
# and simulated bears visibly walked into villages. With beta = 0.6 a score
# difference of 6 points (forest versus residential area) corresponds to a
# factor of roughly 400. Tested on the real terrain of the camera region
# at 0.6 / 1.0 / 1.5: a value of 1.0 clearly lowers the settlement share
# without making the choice effectively deterministic, which would destroy
# the random character of the model.
SELECTION_BETA = 1.0

# How far ahead the bear "looks" when choosing a heading, in metres. The
# original StepSelectionModel uses the same value as perception_distance.
# It is required because step lengths (median around 45 m/h) are much
# smaller than the terrain grid size (150 m): without look-ahead all
# candidate headings fall into the same grid cell, receive the same score,
# and the choice would again be purely random.
DEFAULT_TERRAIN_PERCEPTION_M = 200

# How strongly a step prefers roughly the same heading as the previous one
# (directional persistence, a correlated random walk). Kept on the same
# order of magnitude as TERRAIN_PREFERENCE so that the two signals can
# balance each other.
DEFAULT_PERSISTENCE_WEIGHT = 2.5


def _score_terrain(features: dict) -> float:
    """
    Score a terrain feature dictionary. If it contains tag-qualified keys
    such as "landuse=forest" the more precise table is used; older caches
    without tag context fall back to the value-based table automatically.
    """
    if any("=" in k for k in features):
        return sum(w for key, w in TERRAIN_PREFERENCE_QUALIFIED.items() if features.get(key))
    return sum(w for key, w in TERRAIN_PREFERENCE.items() if features.get(key))


def _angular_diff_deg(a: float, b: float) -> float:
    """Smallest angle between two headings, in degrees (0-180)."""
    d = abs(a - b) % 360
    return d if d <= 180 else 360 - d


# --- Cluster-based heading selection after Geyer/Melzer/Duennweber ------
#
# Reference: J. Geyer, M. Melzer, J. Duennweber, A. Sarkar, "Human Step
# Movement Imitation for Training Privacy-Aware Intelligent Environments",
# IEEE, section III-B, formula (1):
#
#     P = SUM(w_i * p_i) / SUM(w_i)
#
# In that paper P is the position of a foot on a sensor mat, p_i the
# centroid of an activated triangular sensor field and w_i its capacitance
# value. The essential idea is that instead of deciding on ONE grid field,
# a continuous position is computed from all activated fields, biased
# towards the more strongly activated ones. A separation into individual
# feet precedes this; without it the mean of two feet would lie between
# them, where there is no foot at all.
#
# What is transferred here, and what is not:
#   - Formula (1) itself is adopted, together with the order "separate
#     first, then take the weighted mean".
#   - The separation method of the paper is NOT adopted. There, mean shift
#     does not cluster grid fields but pixel embeddings in a learned
#     16-dimensional space (U-Net with a discriminative loss). No such
#     embedding exists here, and it would be unnecessary for a regular
#     terrain grid: neighbouring cells are already adjacent in space, so a
#     connected-component search (flood fill) separates the areas directly.
#     This is an analogue of the GOAL of that step, not of its method.
#   - In the paper the weights w_i are capacitance values and therefore
#     non-negative. Terrain scores, by contrast, are signed (forest +3,
#     motorway -4). A centroid with negative weights is not meaningful: the
#     denominator can approach zero and the result can jump arbitrarily far
#     away. Only ATTRACTIVE cells therefore enter the mean, weighted by
#     their score shifted by the attractiveness threshold (see
#     _terrain_clusters).

# Score from which a grid cell counts as attractive. A threshold of 1.0
# admits forest (3.0), nature reserve (3.0) and scrub (2.0), just includes
# plain meadow and wetland (1.0) and excludes farmland (-0.5).
TERRAIN_ATTRACTIVE_MIN = 1.0

# Radius within which the terrain is treated as an area. At a grid size of
# 167 m, 350 m covers roughly four cells in every direction: far enough to
# capture an adjacent patch of forest, close enough that the resulting
# heading still relates to the next step.
CLUSTER_SEARCH_RADIUS_M = 350

# Number of freely drawn headings offered in addition to the cluster
# headings. Without them the bear could only ever steer towards clusters;
# with the typical two or three clusters the model would be almost
# deterministic and the bear would never leave a patch of forest again.
NUM_FREE_CANDIDATES = 8

# How strongly the mere EXISTENCE of an attractive area within range
# attracts the heading choice, in addition to the score of the route there.
#
# Without this term the transfer would have no effect: a cluster heading
# would be just another candidate scored exactly like the free ones
# (terrain over the first 200 m or so, plus directional persistence). The
# actual information carried by formula (1), namely that a large mass of
# attractive terrain lies in THIS direction, would be lost. In the paper
# the activation mass is precisely the signal that pulls the position.
#
# The bonus grows with cluster mass but is capped by tanh: a forest twice
# the size should be more attractive, but not without limit, otherwise the
# choice becomes deterministic.
CLUSTER_ATTRACTION = 4.0
CLUSTER_MASS_SCALE = 10.0


def _habitat_score(features: dict) -> float:
    """
    Score a grid cell by cover and habitat ONLY; roads, settlements and
    railway lines are excluded.

    Why this is separate from _score_terrain(): that function sums all
    features of a cell, including the negative ones. A forest cell with a
    forest track in it therefore scores 3.0 - 1.5 = 1.5. Measured on the
    real camera area, 11.5 % of cells carry a forest tag but only 6.1 %
    still reach 1.0 in the summed score: the forests are cut apart by
    tracks and fall into single-cell clusters.

    For the question "where is a contiguous patch of forest" that is the
    wrong quantity, because a track does not turn forest into non-forest.
    The penalty terms still apply where they belong, namely in scoring the
    individual step target (_score_terrain at the perception point).
    """
    if any("=" in k for k in features):
        table = TERRAIN_PREFERENCE_QUALIFIED
    else:
        table = TERRAIN_PREFERENCE
    return sum(w for key, w in table.items() if w > 0 and features.get(key))


def _terrain_clusters(
    current: tuple[float, float],
    terrain_cache: "TerrainCache",
    search_radius_m: float = CLUSTER_SEARCH_RADIUS_M,
    query_radius_m: int = 150,
    attractive_min: float = TERRAIN_ATTRACTIVE_MIN,
) -> list[dict]:
    """
    Find attractive terrain areas within range and return ONE continuous
    target point per area, following formula (1) of the paper.

    Procedure:
      1. Fetch all cached grid cells within range in a single SQLite query,
         without any network access.
      2. Score every cell with _habitat_score() and discard all cells below
         the attractiveness threshold.
      3. Group the remaining cells into contiguous areas by flood fill over
         the 8-neighbourhood. This is the step that separates the feet in
         the paper. Without it the centroid of a forest to the north and
         one to the south would fall exactly between them, possibly in the
         middle of a village.
      4. Form the weighted centroid of each area according to formula (1).
         The weight of a cell is its score minus the threshold plus a small
         offset, so that a cell exactly at the threshold still counts and
         all weights stay positive (see the comment block above).

    Returns:
        A list of {"center": (lat, lon), "weight_sum": float,
        "n_cells": int}, sorted by weight_sum in descending order. Empty if
        nothing attractive is within range.
    """
    lat, lon = current
    # Range in degrees: meridians converge towards the poles.
    dlat = search_radius_m / 111_320.0
    dlon = search_radius_m / (111_320.0 * max(0.2, math.cos(math.radians(lat))))

    cells = terrain_cache.get_cells_in_box(
        lat - dlat, lon - dlon, lat + dlat, lon + dlon, radius=query_radius_m
    )
    if not cells:
        return []

    g = getattr(terrain_cache, "grid_size_deg", 0.0015)

    # Map to integer grid indices; only then can adjacency be tested
    # without floating-point comparisons.
    scored: dict[tuple[int, int], tuple[float, float, float]] = {}
    for lat_key, lon_key, features in cells:
        s = _habitat_score(features)
        if s < attractive_min:
            continue
        i, j = int(round(lat_key / g)), int(round(lon_key / g))
        scored[(i, j)] = (s, lat_key, lon_key)

    if not scored:
        return []

    # Flood fill over the 8-neighbourhood (connected components).
    # Deliberately iterative with an explicit stack rather than recursive:
    # large contiguous forest areas would otherwise exceed the recursion
    # limit.
    neighbours = [(di, dj) for di in (-1, 0, 1) for dj in (-1, 0, 1) if (di, dj) != (0, 0)]
    seen: set[tuple[int, int]] = set()
    clusters = []

    for start in scored:
        if start in seen:
            continue
        stack, members = [start], []
        seen.add(start)
        while stack:
            cur = stack.pop()
            members.append(cur)
            ci, cj = cur
            for di, dj in neighbours:
                nb = (ci + di, cj + dj)
                if nb in scored and nb not in seen:
                    seen.add(nb)
                    stack.append(nb)

        # Formula (1): P = SUM(w_i * p_i) / SUM(w_i)
        # The offset of 0.5 keeps a cell exactly at the threshold from
        # dropping out with a weight of zero.
        w_sum = 0.0
        lat_acc = lon_acc = 0.0
        for m in members:
            s, clat, clon = scored[m]
            w = (s - attractive_min) + 0.5
            w_sum += w
            lat_acc += w * clat
            lon_acc += w * clon
        if w_sum <= 0:
            continue
        clusters.append({
            "center": (lat_acc / w_sum, lon_acc / w_sum),
            "weight_sum": w_sum,
            "n_cells": len(members),
        })

    clusters.sort(key=lambda c: c["weight_sum"], reverse=True)
    return clusters


def choose_weighted_direction(
    current: tuple[float, float],
    step_length_m: float,
    rng: random.Random,
    terrain_cache: "TerrainCache | None" = None,
    prev_direction: float | None = None,
    persistence_weight: float = DEFAULT_PERSISTENCE_WEIGHT,
    num_candidates: int = 8,
    query_radius_m: int = 150,
    terrain_perception_m: float = DEFAULT_TERRAIN_PERCEPTION_M,
    selection_beta: float = SELECTION_BETA,
    terrain_samples: int = 3,
    cluster_attraction: float = CLUSTER_ATTRACTION,
) -> tuple[tuple[float, float], float]:
    """
    Choose the next heading by a weighted random draw from a candidate set.

    Candidates come from two sources:
      - Headings towards attractive terrain areas, determined by the method
        of Geyer/Melzer/Duennweber (formula (1); see _terrain_clusters and
        the comment block above it). Only when a terrain_cache is supplied.
      - Stratified random headings covering the full circle, so that the
        model stays stochastic and no heading is unreachable.

    Candidates are then scored by two signals that may be combined:

      1. Terrain preference (see TERRAIN_PREFERENCE), if a terrain_cache is
         given. Makes the path more plausible in the landscape, favouring
         forest over roads and settlements.
      2. Directional persistence (correlated random walk), if
         prev_direction is given. Candidates close to the previous heading
         are preferred and reversals penalised. This turns the path into
         recognisable travel instead of jitter in place, which is what pure
         per-step randomness produced: the bear tended to stay near its
         starting point.

    Both signals are independently optional and combined additively when
    both are present. The selection remains a weighted random draw rather
    than a strict maximum; otherwise the result would be a deterministic
    path rather than a random walk.

    Returns:
        (destination, chosen_direction_deg). The heading is returned so
        that the next call can pass it as prev_direction.
    """
    # -----------------------------------------------------------------
    # 1) Headings towards attractive terrain areas (formula (1), above)
    # -----------------------------------------------------------------
    # One (heading, bonus) pair per candidate. Only cluster headings
    # receive a bonus; free headings do not.
    directions: list[tuple[float, float]] = []
    if terrain_cache is not None:
        for cl in _terrain_clusters(current, terrain_cache,
                                    query_radius_m=query_radius_m):
            d = GeoToolBox.calculate_direction(current, cl["center"])
            bonus = cluster_attraction * math.tanh(cl["weight_sum"] / CLUSTER_MASS_SCALE)
            directions.append((d % 360, bonus))

    # -----------------------------------------------------------------
    # 2) Freely drawn headings, stratified over the full circle.
    #
    # Rationale: the earlier version used eight fixed headings on a
    # 45-degree grid with only +/-15 degrees of jitter. Each sector
    # therefore covered only 30 of its 45 degrees, leaving the ranges in
    # between (for example 16-29 degrees) fundamentally unreachable, a
    # third of all headings. Measured over 3,840 decisions, not a single
    # one fell into those gaps.
    #
    # With +/-22.5 degrees the sectors meet without gaps and cover the full
    # circle. The stratification, exactly one candidate per sector, is kept
    # deliberately: it spreads candidates more evenly over the circle than
    # a plain uniform draw, in which several candidates can by chance pile
    # up in the same compass direction within one step.
    #
    # These candidates are retained even WITH terrain data; otherwise the
    # bear could only steer towards clusters and would never leave a patch
    # of forest.
    # -----------------------------------------------------------------
    n_free = num_candidates if terrain_cache is None else NUM_FREE_CANDIDATES
    sector = 360.0 / n_free
    for i in range(n_free):
        directions.append(((sector * i + rng.uniform(-sector / 2, sector / 2)) % 360, 0.0))

    candidates = []
    for direction, cluster_bonus in directions:
        score = cluster_bonus
        dest = GeoToolBox.destination_point(current, direction, step_length_m)
        if terrain_cache is not None:
            # Score the terrain not only at the end of the step but along
            # the route up to a perception point further ahead. Steps are
            # often shorter than the grid size (167 m), so otherwise all
            # candidates fall into the same cell and receive identical
            # scores.
            #
            # Several samples instead of only the end point (measurements
            # in ANPASSUNGEN.md, item 8): a cluster heading points at the
            # centroid of a forest patch that may well lie BEHIND a
            # village. Scoring only the end point makes such a route look
            # attractive and sends the bear straight through the
            # settlement; sampling along the way makes the settlement
            # count.
            look_ahead = max(step_length_m, terrain_perception_m)
            samples = []
            for k in range(1, terrain_samples + 1):
                d_k = look_ahead * k / terrain_samples
                pt = GeoToolBox.destination_point(current, direction, d_k)
                samples.append(_score_terrain(
                    terrain_cache.get_features(pt[0], pt[1], radius=query_radius_m)
                ))
            score += sum(samples) / len(samples)

        if prev_direction is not None:
            angle_diff = _angular_diff_deg(direction, prev_direction)
            # cos(0) = 1 for the same heading (full bonus) down to
            # cos(180) = -1 for a reversal (full penalty)
            score += persistence_weight * math.cos(math.radians(angle_diff))

        candidates.append((dest, direction, score))

    # Exponential weighting as customary in step selection functions:
    # probability proportional to exp(beta * score). Linear weighting made
    # the difference between forest and settlement only a factor of about
    # 2 to 3, too little to keep the bear out of villages. Subtracting the
    # maximum serves numerical stability only and does not change the
    # relative probabilities.
    scores = [c[2] for c in candidates]
    max_score = max(scores)
    weights = [math.exp(selection_beta * (sc - max_score)) for sc in scores]

    chosen_dest, chosen_direction, _ = rng.choices(candidates, weights=weights, k=1)[0]
    return chosen_dest, chosen_direction


def simulate_free_path(
    start_lat: float,
    start_lng: float,
    start_time: datetime,
    duration_hours: int,
    gender: str,
    age: str,
    season: str,
    bear_speeds: "BearSpeeds",
    source: str = SIM_SOURCE,
    seed: int | None = None,
    terrain_cache: "TerrainCache | None" = None,
    use_directional_persistence: bool = True,
    persistence_weight: float = DEFAULT_PERSISTENCE_WEIGHT,
    terrain_perception_m: float = DEFAULT_TERRAIN_PERCEPTION_M,
    selection_beta: float = SELECTION_BETA,
) -> list[dict]:
    """
    Simulate a path from a free starting point, hour by hour.

    Uses the same convention as generate_alternative_steps() in the
    original model: the value from bear_speeds is already the typical step
    length in kilometres for that hour, season, age and sex, so it is not
    multiplied by time again.

    Args:
        terrain_cache: if given, each heading is additionally weighted by
            terrain, favouring forest. This makes the path more realistic
            but requires (cached) Overpass data.
        use_directional_persistence: whether the heading carries over from
            step to step (correlated random walk) instead of being redrawn
            from scratch every time. Enabled by default, because redrawing
            at every step makes the simulated bear jitter in place rather
            than travel plausibly.

    Returns:
        A list of {"time": datetime, "lat": float, "lng": float}.
    """
    if gender not in VALID_GENDERS or age not in VALID_AGES or season not in VALID_SEASONS:
        raise ValueError(
            f"Invalid combination gender={gender!r} age={age!r} season={season!r}. "
            f"Allowed: gender in {VALID_GENDERS}, age in {VALID_AGES}, season in {VALID_SEASONS}"
        )

    rng = random.Random(seed)

    path = [{"time": start_time, "lat": start_lat, "lng": start_lng}]
    current = (start_lat, start_lng)
    current_time = start_time
    prev_direction: float | None = None  # no history yet on the first step

    for _ in range(int(duration_hours)):
        hour = current_time.hour
        median_speed_kmh = bear_speeds.get_median_speed_for_type_and_time(
            gender, age, season, hour, source
        )
        current_time += timedelta(hours=1)

        if median_speed_kmh is None:
            # No data for this hour: hold the position (no step) while
            # time continues to advance. The heading is kept for the next
            # actual step so that persistence is not broken.
            path.append({"time": current_time, "lat": current[0], "lng": current[1]})
            continue

        step_length_m = median_speed_kmh * 1000

        if terrain_cache is not None or use_directional_persistence:
            current, prev_direction = choose_weighted_direction(
                current, step_length_m, rng,
                terrain_cache=terrain_cache,
                prev_direction=prev_direction if use_directional_persistence else None,
                persistence_weight=persistence_weight,
                terrain_perception_m=terrain_perception_m,
                selection_beta=selection_beta,
            )
        else:
            direction_deg = rng.uniform(0, 360)  # fully random, unweighted baseline
            current = GeoToolBox.destination_point(current, direction_deg, step_length_m)
            prev_direction = direction_deg

        path.append({"time": current_time, "lat": current[0], "lng": current[1]})

    return path


# Known placeholder device IDs produced by failed ID detection during the
# e-mail import; also referenced in activity_overlap.py.
PLACEHOLDER_DEVICE_IDS = {"199999", "999999"}


def get_real_events_for_camera(db: "WildlifeDatabase", device_id: str) -> list[datetime]:
    """
    Full timestamps, not just hours, of all real photographs taken at ONE
    specific camera, read from bears_images_unified, which combines the
    file system and e-mail sources and is more complete than the older
    image_metadata table.

    Required in order to (a) pick a real starting time for the simulation
    and (b) mark real trigger times on the animation timeline for
    comparison.
    """
    if device_id in PLACEHOLDER_DEVICE_IDS:
        return []
    rows = db.execute_query(
        "SELECT timestamp FROM bears_images_unified WHERE device_id = %s AND timestamp IS NOT NULL",
        [device_id],
    )
    events = []
    for r in rows or []:
        ts = r.get("timestamp")
        try:
            dt = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
            events.append(dt)
        except (ValueError, TypeError):
            continue
    return sorted(events)


def get_photo_counts_by_camera(db: "WildlifeDatabase") -> "dict[str, int] | None":
    """
    Number of real photographs per camera, in ONE query for all devices.

    Required for the clickable camera markers. Deliberately not solved by
    repeated get_real_events_for_camera() calls, which would mean 20
    individual queries per page load.

    Device IDs are normalised exactly as the camera CSV is
    (_normalize_device_id); otherwise "3002.0" from the CSV and "003002"
    from the database would not match. Placeholder devices from failed ID
    detection during the e-mail import are excluded.

    Returns:
        {device_id: count}, or None if the query failed.

        None and {} are DELIBERATELY different: {} means "queried, but no
        photographs at any camera", None means "could not be queried".
        Cameras that were never triggered do not appear in the result at
        all because of the GROUP BY, so the caller may treat a missing key
        as 0 as soon as the result is not None. Returning {} on failure
        would make the map report "no photographs" instead of "unknown".
    """
    try:
        rows = db.execute_query(
            "SELECT device_id, COUNT(*) AS n FROM bears_images_unified "
            "WHERE device_id IS NOT NULL GROUP BY device_id"
        )
    except Exception as e:
        print(f"[japan_comparison] Photo counts not retrievable: {e}")
        return None
    if rows is None:
        # execute_query() re-raises errors and otherwise always returns a
        # list. This check is purely defensive, so that a future None is
        # not silently passed on as "no photographs".
        return None

    counts: dict[str, int] = {}
    for r in rows or []:
        did = _normalize_device_id(r.get("device_id"))
        if did in PLACEHOLDER_DEVICE_IDS:
            continue
        counts[did] = counts.get(did, 0) + int(r.get("n") or 0)
    return counts


def simulate_multiple_bears_from_sighting(
    start_lat: float,
    start_lng: float,
    start_time: datetime,
    n_bears: int,
    duration_hours: int,
    bear_speeds: "BearSpeeds",
    seed: int = 42,
    terrain_cache: "TerrainCache | None" = None,
    use_directional_persistence: bool = True,
) -> list[dict]:
    """
    Simulate N independent bears that all start at the SAME real photo
    position and time, as if that were the moment of an actual sighting.
    Each bear is given a random sex, age and season in order to average
    over the unknown demography, and its own random seed so that the paths
    differ visibly.

    Returns:
        A list of {"bear_index": int, "gender", "age", "season", "path"}.
    """
    rng = random.Random(seed)
    bears = []
    for i in range(n_bears):
        gender = VALID_GENDERS[rng.randrange(len(VALID_GENDERS))]
        age = VALID_AGES[rng.randrange(len(VALID_AGES))]
        season = VALID_SEASONS[rng.randrange(len(VALID_SEASONS))]
        bear_seed = rng.randrange(10_000_000)

        path = simulate_free_path(
            start_lat=start_lat, start_lng=start_lng, start_time=start_time,
            duration_hours=duration_hours, gender=gender, age=age, season=season,
            bear_speeds=bear_speeds, seed=bear_seed, terrain_cache=terrain_cache,
            use_directional_persistence=use_directional_persistence,
        )
        bears.append({"bear_index": i, "gender": gender, "age": age, "season": season, "path": path})
    return bears


def check_db_reachable(db: "WildlifeDatabase") -> bool:
    """
    Explicit one-off connection check. Required because WildlifeDatabase
    catches connection errors internally in some paths, printing a message
    without raising, so a try/except around get_images() would NOT detect
    the failure.
    """
    try:
        conn = db._get_connection()
        conn.close()
        return True
    except Exception:
        return False


def get_real_photo_hours(db: "WildlifeDatabase", device_id: str) -> list[int]:
    """
    Return the hours of day (0-23) at which photographs were actually
    triggered at a given camera, read from MariaDB through the existing
    get_images() method.

    Database reachability is assumed to have been checked beforehand with
    check_db_reachable(). This function therefore presumes a working
    connection and returns an empty list when a camera genuinely has no
    photographs, which is not to be confused with the database being down.
    """
    images = db.get_images(device_id=device_id, limit=10000)
    records = images.to_dict("records") if hasattr(images, "to_dict") else (images or [])

    hours = []
    for img in records:
        ts = img.get("timestamp")
        if not ts:
            continue
        try:
            dt = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
            hours.append(dt.hour)
        except (ValueError, TypeError):
            continue
    return hours


def compare_to_real_cameras(
    simulated_path: list[dict],
    cameras: list[dict],
    db: "WildlifeDatabase",
    db_reachable: bool,
    proximity_m: float = 200,
    hour_tolerance: int = 2,
) -> list[dict]:
    """
    For every simulated waypoint, check whether a real camera is nearby
    (closer than proximity_m) AND whether photographs were actually
    triggered at that camera at a similar time of day (within
    hour_tolerance).

    db_reachable must have been determined beforehand with
    check_db_reachable(). When it is False no query is attempted at all,
    which would otherwise stall the run on repeated timeouts.
    """
    hits = []
    photo_hours_cache: dict[str, list[int]] = {}

    for point in simulated_path:
        sim_point = (point["lat"], point["lng"])
        for cam in cameras:
            dist_m = geodesic(sim_point, (cam["lat"], cam["lng"])).meters
            if dist_m > proximity_m:
                continue

            device_id = cam["device_id"]
            real_hours: list[int] = []
            if db_reachable:
                if device_id not in photo_hours_cache:
                    photo_hours_cache[device_id] = get_real_photo_hours(db, device_id)
                real_hours = photo_hours_cache[device_id]

            sim_hour = point["time"].hour
            time_match = db_reachable and any(
                min(abs(sim_hour - h), 24 - abs(sim_hour - h)) <= hour_tolerance
                for h in real_hours
            )

            hits.append({
                "sim_time": point["time"],
                "sim_lat": point["lat"],
                "sim_lng": point["lng"],
                "device_id": device_id,
                "distance_m": round(dist_m, 1),
                "time_match": time_match,
                "query_ok": db_reachable,
                "real_photo_hours_at_camera": sorted(set(real_hours)),
            })

    return hits


def run_experiment(
    gender: str = "F",
    age: str = "A",
    season: str = "summer",
    duration_hours: int = 24,
    start_time: datetime | None = None,
    start_camera_index: int = 0,
    proximity_m: float = 200,
    hour_tolerance: int = 2,
    seed: int | None = 42,
    use_terrain: bool = False,
) -> dict:
    """
    Complete run: load, simulate, compare, return the result.

    use_terrain=True selects headings with terrain weighting (see
    choose_weighted_direction). This needs internet access the first time
    each grid cell is touched; afterwards the data is cached locally in
    terrain_cache.db.

    use_terrain=False (default) uses unweighted random headings and
    requires no Overpass queries. Faster, but blind to the landscape.
    """
    cameras = load_japan_cameras()
    if not cameras:
        return {"error": "No Japanese camera locations found. They come from MariaDB (deterrent_devices), so the university VPN has to be active."}

    start_camera_index = max(0, min(start_camera_index, len(cameras) - 1))
    start_cam = cameras[start_camera_index]

    dbcon = DatabaseConnection(SIM_DB_PATH)
    bear_speeds = BearSpeeds(dbcon)

    if start_time is None:
        start_time = datetime(2024, 6, 1, 6, 0, 0)

    terrain_cache = TerrainCache() if use_terrain else None

    path = simulate_free_path(
        start_lat=start_cam["lat"], start_lng=start_cam["lng"],
        start_time=start_time, duration_hours=duration_hours,
        gender=gender, age=age, season=season,
        bear_speeds=bear_speeds, seed=seed,
        terrain_cache=terrain_cache,
    )

    result = {
        "start_camera": start_cam,
        "path": path,
        "hits": [],
        "db_available": False,
    }

    try:
        db = WildlifeDatabase()
        db_reachable = check_db_reachable(db)
        result["db_available"] = db_reachable
        if not db_reachable:
            print("  [note] MariaDB not reachable (is the VPN active?). The "
                  "time comparison is skipped; the simulated path remains valid.")
        result["hits"] = compare_to_real_cameras(
            path, cameras, db, db_reachable=db_reachable,
            proximity_m=proximity_m, hour_tolerance=hour_tolerance,
        )
    except Exception as e:
        result["db_error"] = str(e)

    return result


if __name__ == "__main__":
    use_terrain = "--terrain" in sys.argv

    print("=" * 70)
    if use_terrain:
        print("Japan transfer experiment (with terrain weighting, locally cached)")
    else:
        print("Japan transfer experiment (baseline, without terrain weighting)")
    print("=" * 70)

    res = run_experiment(use_terrain=use_terrain)

    if "error" in res:
        print(res["error"])
        sys.exit(1)

    cam = res["start_camera"]
    print(f"\nStart: camera {cam['device_id']} at {cam['lat']:.5f}, {cam['lng']:.5f}")
    print(f"Simulated path: {len(res['path'])} positions")
    print(f"  First position: {res['path'][0]}")
    print(f"  Last position:  {res['path'][-1]}")

    if not res["db_available"]:
        print(f"\n[note] Database comparison not possible (is the VPN active?): "
              f"{res.get('db_error', 'connection failed')}")
        print("The simulated path itself was generated successfully.")
        print(f"\n{len(res['hits'])} spatial approach(es) to cameras found "
              f"(< 200 m, without time comparison):")
        for h in res["hits"]:
            print(f"  {h['sim_time']} -> camera {h['device_id']} ({h['distance_m']} m away)")
    else:
        hits = res["hits"]
        print(f"\n{len(hits)} approach(es) to Japanese cameras found (< 200 m):")
        for h in hits:
            match_str = "yes" if h["time_match"] else "no"
            print(f"  {h['sim_time']} -> camera {h['device_id']} "
                  f"({h['distance_m']} m away) | time matches real photographs: {match_str} "
                  f"(real photo hours there: {h['real_photo_hours_at_camera']})")
        if not hits:
            print("  No approaches. The cameras are probably too far apart for a "
                  "24 h radius; try a longer simulation duration or a different "
                  "starting point.")