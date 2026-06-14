from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db import get_db
from app.schemas.query import SuitabilityQueryRequest, SuitabilityQueryResponse, CategoryResponse
from app.models.observation import PredictionLog
from datetime import datetime

router = APIRouter()


@router.get('/nearby/competitors')
async def nearby_competitors(latitude: float, longitude: float, radius: int = 500, limit: int = 100, db: Session = Depends(get_db)):
    """Return nearby competitor POIs from observations within radius (meters).
    Query params: latitude, longitude, radius (meters), limit
    """
    point_sql = "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography"
    sql = text(f"""
        SELECT id, biz_category, ST_X(geom::geometry) AS lon, ST_Y(geom::geometry) AS lat, pop_density
        FROM observations
        WHERE ST_DWithin(geom::geography, {point_sql}, :radius)
        LIMIT :limit
    """)
    rows = db.execute(sql, {"lon": longitude, "lat": latitude, "radius": radius, "limit": limit}).mappings().all()
    results = []
    for r in rows:
        results.append({
            "id": int(r['id']),
            "biz_category": r['biz_category'],
            "latitude": float(r['lat']),
            "longitude": float(r['lon']),
            "pop_density": float(r['pop_density'] or 0)
        })
    return {"count": len(results), "results": results}


@router.get('/layers/pop_density')
async def layer_pop_density(latitude: float, longitude: float, radius: int = 2000, db: Session = Depends(get_db)):
    """Return observation points and pop_density within radius for client-side heatmap.
    Keep result size limited for responsiveness.
    """
    point_sql = "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography"
    sql = text(f"""
        SELECT ST_X(geom::geometry) AS lon, ST_Y(geom::geometry) AS lat, pop_density
        FROM observations
        WHERE ST_DWithin(geom::geography, {point_sql}, :radius)
        LIMIT 1000
    """)
    rows = db.execute(sql, {"lon": longitude, "lat": latitude, "radius": radius}).mappings().all()
    pts = [{"lat": float(r['lat']), "lon": float(r['lon']), "pop_density": float(r['pop_density'] or 0)} for r in rows]
    return {"count": len(pts), "points": pts}



@router.post("/query", response_model=SuitabilityQueryResponse)
async def query_suitability(
    request: SuitabilityQueryRequest,
    db: Session = Depends(get_db)
):
    """
    Query spatial suitability for a given location using PostGIS functions.
    Uses the `observations` table as a POI layer to compute nearby counts, averages,
    and nearest distances. Returns a heuristic suitability score and factor breakdown.
    """
    lat = request.latitude
    lon = request.longitude
    category = request.business_category
    radius = int(request.radius_meters or 500)

    # Build point SQL (WGS84)
    point_sql = "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography"

    # Competitor counts using dynamic analysis radius (meters)
    counts_sql = text(f"""
        SELECT
            SUM(CASE WHEN ST_DWithin(geom::geography, {point_sql}, 300) THEN 1 ELSE 0 END) AS comp_300,
            SUM(CASE WHEN ST_DWithin(geom::geography, {point_sql}, 500) THEN 1 ELSE 0 END) AS comp_500,
            SUM(CASE WHEN ST_DWithin(geom::geography, {point_sql}, 1000) THEN 1 ELSE 0 END) AS comp_1k,
            SUM(CASE WHEN ST_DWithin(geom::geography, {point_sql}, :radius) THEN 1 ELSE 0 END) AS comp_radius
        FROM observations
        WHERE biz_category IS NULL OR biz_category != :category
    """)

    res_counts = db.execute(counts_sql, {"lon": lon, "lat": lat, "category": category, "radius": radius}).mappings().first()
    comp_300 = int(res_counts['comp_300'] or 0)
    comp_500 = int(res_counts['comp_500'] or 0)
    comp_1k = int(res_counts['comp_1k'] or 0)
    comp_radius = int(res_counts['comp_radius'] or 0)

    # Average traffic within the analysis radius
    traffic_sql = text(f"""
        SELECT
            AVG(traffic_morning) AS avg_morning,
            AVG(traffic_midday) AS avg_midday,
            AVG(traffic_evening) AS avg_evening
        FROM observations
        WHERE ST_DWithin(geom::geography, {point_sql}, :radius)
    """)
    res_traffic = db.execute(traffic_sql, {"lon": lon, "lat": lat, "radius": radius}).mappings().first()
    avg_morning = float(res_traffic['avg_morning'] or 0)
    avg_midday = float(res_traffic['avg_midday'] or 0)
    avg_evening = float(res_traffic['avg_evening'] or 0)
    traffic_total = avg_morning + avg_midday + avg_evening

    # Nearest observation distance (meters)
    nearest_sql = text(f"""
        SELECT MIN(ST_Distance(geom::geography, {point_sql})) AS nearest_m
        FROM observations
    """)
    res_nearest = db.execute(nearest_sql, {"lon": lon, "lat": lat}).mappings().first()
    nearest_m = float(res_nearest['nearest_m'] or 0)

    # Population density: average within the analysis radius
    pop_sql = text(f"""
        SELECT AVG(pop_density) AS avg_pop
        FROM observations
        WHERE ST_DWithin(geom::geography, {point_sql}, :radius)
    """)
    res_pop = db.execute(pop_sql, {"lon": lon, "lat": lat, "radius": radius}).mappings().first()
    pop_density = float(res_pop['avg_pop'] or 0)

    # Average distance/accessibility indicators within the analysis radius.
    # These are based on the existing observed fields in the observations table.
    access_sql = text(f"""
        SELECT
            AVG(dist_transport) AS avg_dist_transport,
            AVG(dist_market) AS avg_dist_market,
            AVG(dist_road) AS avg_dist_road,
            AVG(CASE WHEN road_type THEN 1 ELSE 0 END) AS avg_road_type
        FROM observations
        WHERE ST_DWithin(geom::geography, {point_sql}, :radius)
    """)

    res_access = db.execute(
        access_sql,
        {"lon": lon, "lat": lat, "radius": radius}
    ).mappings().first()

    dist_transport = float(res_access["avg_dist_transport"] or 0)
    dist_market = float(res_access["avg_dist_market"] or 0)
    dist_road = float(res_access["avg_dist_road"] or 0)
    road_type = float(res_access["avg_road_type"] or 0)

    # Send PostGIS-derived features into the trained Random Forest pipeline.
    base_features = {
        "comp_count_300": comp_300,
        "comp_count_500": comp_500,
        "comp_count_1k": comp_1k,
        "traffic_morning": avg_morning,
        "traffic_midday": avg_midday,
        "traffic_evening": avg_evening,
        "dist_transport": dist_transport,
        "dist_market": dist_market,
        "dist_road": dist_road,
        "pop_density": pop_density,
        "road_type": road_type
    }

    model_result = predict_suitability(base_features)

    label = model_result["label"]
    suitability_score = model_result["confidence"] if model_result["confidence"] is not None else 0.0

    # Keep normalized values for factor explanation display.
    comp_score = 1.0 / (1.0 + comp_500)
    traffic_score = min(1.0, traffic_total / 400.0)

    avg_access_distance = (dist_transport + dist_market + dist_road) / 3.0
    access_score = 1.0 / (1.0 + avg_access_distance)

    # Factor assessments
    def assess(val, bounds=(0.33, 0.66)):
        if val >= bounds[1]:
            return "high"
        if val >= bounds[0]:
            return "moderate"
        return "low"

    factors = [
        {"name": f"competition_{radius}m", "value": comp_radius, "assessment": assess(comp_score), "shap_value": 0.0},
        {"name": f"traffic_sum_{radius}m", "value": traffic_total, "assessment": assess(traffic_score), "shap_value": 0.0},
        {"name": "accessibility_index", "value": avg_access_distance, "assessment": assess(access_score), "shap_value": 0.0},
        {"name": f"pop_density_{radius}m", "value": pop_density, "assessment": assess(min(1.0, pop_density/600.0)), "shap_value": 0.0}
    ]

    top_positive = [f['name'] for f in factors if f['assessment'] == 'high']
    top_negative = [f['name'] for f in factors if f['assessment'] == 'low']

    # Log query
    try:
        log = PredictionLog(
            latitude=lat,
            longitude=lon,
            business_category=category,
            suitability_score=suitability_score,
            predicted_label=(label == 'strong'),
            created_at=datetime.utcnow()
        )
        db.add(log)
        db.commit()
    except Exception:
        db.rollback()

    return {
        "suitability_score": round(suitability_score, 4),
        "suitability_label": label,
        "factors": factors,
        "top_positive_factors": top_positive,
        "top_negative_factors": top_negative,
        "disclaimer": "This assessment uses a trained spatial suitability model and locally available spatial indicators. It does not predict business success or failure."
    }


@router.get("/categories", response_model=CategoryResponse)
async def list_categories():
    """List available business categories and subtypes."""
    # For now return a small curated set; replace with DB-driven categories if available
    return {
        "categories": ["personal_care", "retail", "food_beverage"],
        "subtypes": {
            "personal_care": ["hair_salon", "barbershop", "beauty_salon", "nail_studio"],
            "retail": ["grocery", "convenience", "clothing"],
            "food_beverage": ["cafe", "restaurant", "fast_food"]
        }
    }
