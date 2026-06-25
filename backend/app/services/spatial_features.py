"""
Computes the spatial feature vector for a candidate (latitude, longitude)
using the same PostGIS operations applied during dataset construction
(see model notebook Section 2):

  - comp_count_300/500/1k : ST_DWithin self-join against `observations`
  - dist_transport/market/road : ST_Distance to the nearest POI, bucketed
    into the 4-level proximity band used throughout the project
  - pop_density, traffic_morning/midday/evening : inverse-distance-weighted
    (IDW) interpolation from the k nearest reference observations

Foot traffic cannot be measured for a location with no business history, so
it is estimated via IDW from nearby reference observations rather than
looked up directly. This is the one feature that genuinely differs in
computation between "training data construction" (a direct field count) and
"inference for a candidate pin" (a spatial estimate) — documented here for
that reason.
"""

from typing import Optional
from sqlalchemy import text
from sqlalchemy.orm import Session

# Proximity bands, consistent with Table 5 of the research proposal and the
# model notebook: 0-50m / 50-150m / 150-400m / >400m
DIST_BANDS = [(0, 50), (50, 150), (150, 400), (400, float("inf"))]

# Neighbours used for IDW interpolation of traffic and population density
IDW_K = 8
IDW_POWER = 2
IDW_EPSILON = 1.0  # metres, avoids division by zero at distance 0


def _distance_to_band(distance_m: float) -> int:
    for band, (lo, hi) in enumerate(DIST_BANDS):
        if lo <= distance_m < hi:
            return band
    return 3


def _competitor_counts(db: Session, lat: float, lon: float) -> dict:
    sql = text("""
        SELECT
            COUNT(*) FILTER (WHERE ST_DWithin(geom::geography, pt::geography, 300))  AS c300,
            COUNT(*) FILTER (WHERE ST_DWithin(geom::geography, pt::geography, 500))  AS c500,
            COUNT(*) FILTER (WHERE ST_DWithin(geom::geography, pt::geography, 1000)) AS c1k
        FROM observations,
             LATERAL (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) AS pt) AS p
    """)
    row = db.execute(sql, {"lon": lon, "lat": lat}).mappings().first()
    return {
        "comp_count_300": int(row["c300"] or 0),
        "comp_count_500": int(row["c500"] or 0),
        "comp_count_1k":  int(row["c1k"] or 0),
    }


def _nearest_poi_distance(db: Session, table: str, lat: float, lon: float) -> Optional[float]:
    sql = text(f"""
        SELECT MIN(ST_Distance(
            geom::geography,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
        )) AS dist_m
        FROM {table}
    """)
    row = db.execute(sql, {"lon": lon, "lat": lat}).mappings().first()
    return float(row["dist_m"]) if row and row["dist_m"] is not None else None


def _idw_interpolate(db: Session, lat: float, lon: float) -> dict:
    """IDW interpolation of traffic and population density from the
    IDW_K nearest reference observations, ordered by PostGIS KNN (<->)."""
    sql = text("""
        SELECT
            traffic_morning, traffic_midday, traffic_evening, pop_density,
            ST_Distance(
                geom::geography,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
            ) AS dist_m
        FROM observations
        ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
        LIMIT :k
    """)
    rows = db.execute(sql, {"lon": lon, "lat": lat, "k": IDW_K}).mappings().all()

    if not rows:
        return {"traffic_morning": 0, "traffic_midday": 0, "traffic_evening": 0, "pop_density": 0.0}

    weights = [1.0 / (r["dist_m"] ** IDW_POWER + IDW_EPSILON) for r in rows]
    total_w = sum(weights)

    def weighted(field):
        return sum(r[field] * w for r, w in zip(rows, weights)) / total_w

    return {
        "traffic_morning": round(weighted("traffic_morning")),
        "traffic_midday":  round(weighted("traffic_midday")),
        "traffic_evening": round(weighted("traffic_evening")),
        "pop_density":     round(weighted("pop_density"), 1),
    }


def compute_spatial_features(db: Session, latitude: float, longitude: float) -> dict:
    """
    Returns the 11 base features (Table 5 schema) for a candidate location,
    computed entirely from (latitude, longitude) via PostGIS spatial queries
    against the reference dataset and POI layer.

    `road_type` is not estimable for a candidate location (it describes the
    physical frontage of a specific premises). It is set from the
    nearest-road distance band as a proxy: locations directly on a road
    frontage (dist_road band 0) are assumed tarmac.
    """
    features = {}

    features.update(_competitor_counts(db, latitude, longitude))

    d_market    = _nearest_poi_distance(db, "poi_market", latitude, longitude)
    d_transport = _nearest_poi_distance(db, "poi_transport", latitude, longitude)
    d_road      = _nearest_poi_distance(db, "poi_road", latitude, longitude)

    features["dist_market"]    = _distance_to_band(d_market)    if d_market    is not None else 3
    features["dist_transport"] = _distance_to_band(d_transport) if d_transport is not None else 3
    features["dist_road"]      = _distance_to_band(d_road)      if d_road      is not None else 3

    features.update(_idw_interpolate(db, latitude, longitude))

    features["road_type"] = 1 if features["dist_road"] == 0 else 0

    return features
