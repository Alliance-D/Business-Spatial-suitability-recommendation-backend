"""Public API endpoints — spatial suitability assessment and reference data."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.query import AssessRequest, AssessResponse, CategoryResponse, SchemaResponse
from app.services import spatial_features, model_service, explanation_service

logger = logging.getLogger("kigalisite.query")

router = APIRouter()

# Rate limiter — shared instance from main.py via app.state
limiter = Limiter(key_func=get_remote_address)

DISCLAIMER = (
    "This assessment reflects spatial and environmental patterns at the "
    "neighbourhood level only. It does not predict business success, "
    "profitability, or entrepreneurial outcomes."
)

ALLOWED_RADII = (300, 500, 1000)


@router.get("/health")
async def health(db: Session = Depends(get_db)):
    """Liveness check including database and model artefact status."""
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    model_ok = True
    try:
        model_service.load_pipeline()
        model_service.load_explainer()
    except Exception:
        model_ok = False

    status = "healthy" if (db_ok and model_ok) else "degraded"
    return {"status": status, "database": db_ok, "model": model_ok}


@router.get("/schema", response_model=SchemaResponse)
async def schema():
    """Returns the feature schema used by the model."""
    metadata = model_service.load_metadata()
    return {
        "base_features":       metadata["base_features"],
        "engineered_features": metadata["engineered_features"],
        "distance_bands": {
            "0": "0-50m (Very Close)",
            "1": "50-150m (Close)",
            "2": "150-400m (Moderate)",
            "3": ">400m (Far)",
        },
        "target": metadata["target"],
        "notes": (
            "comp_count_*, dist_*, and pop_density are computed via PostGIS "
            "spatial queries from (latitude, longitude). traffic_* and "
            "road_type are field observations specific to each premises."
        ),
    }


@router.get("/categories", response_model=CategoryResponse)
async def categories():
    """Business categories supported by the deployed model."""
    return {"categories": ["personal_care"]}


@router.post("/assess", response_model=AssessResponse)
@limiter.limit("30/minute")
async def assess(
    request: Request,
    payload: AssessRequest,
    db: Session = Depends(get_db),
):
    """
    Spatial suitability assessment for a candidate location.
    Rate limited to 30 requests per minute per IP address.
    All spatial features are computed server-side via PostGIS.
    """
    if payload.business_category != "personal_care":
        raise HTTPException(
            status_code=400,
            detail="Only the 'personal_care' business category is supported in this version.",
        )

    radius = payload.radius_meters or 500
    if radius not in ALLOWED_RADII:
        radius = min(ALLOWED_RADII, key=lambda r: abs(r - radius))

    try:
        base_features = spatial_features.compute_spatial_features(
            db, payload.latitude, payload.longitude
        )
    except Exception as exc:
        logger.error(f"Spatial feature computation failed | lat={payload.latitude} lon={payload.longitude} | {exc}")
        raise HTTPException(status_code=503, detail=f"Spatial feature computation failed: {exc}")

    try:
        result = model_service.predict(base_features)
    except FileNotFoundError:
        logger.error("Model artefacts not found — inference requested but no model loaded")
        raise HTTPException(status_code=503, detail="Model artefacts not found on server.")
    except Exception as exc:
        logger.error(f"Model inference failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Model inference failed: {exc}")

    probability = result["probability"]
    band        = explanation_service.suitability_band(probability)
    factors     = explanation_service.build_factor_breakdown(
        result["features"], result["shap_values"], radius
    )

    ip = request.client.host if request.client else None
    logger.info(f"Assessment served | band={band} | score={probability:.4f} | ip={ip}")

    # Log the query using raw SQL to match actual prediction_log column names
    try:
        db.execute(text("""
            INSERT INTO prediction_log
                (latitude, longitude, business_category, suitability_score,
                 predicted_label, created_at, ip_address)
            VALUES
                (:lat, :lon, :category, :score, :label, :created_at, :ip)
        """), {
            "lat":        payload.latitude,
            "lon":        payload.longitude,
            "category":   payload.business_category,
            "score":      round(probability, 4),
            "label":      probability >= 0.65,
            "created_at": datetime.utcnow(),
            "ip":         ip,
        })
        db.commit()
    except Exception as log_exc:
        db.rollback()
        logger.warning(f"Prediction log insert failed (non-fatal): {log_exc}")

    return {
        "suitability_probability": round(probability, 4),
        "suitability_band":        band,
        "factors":                 factors,
        "disclaimer":              DISCLAIMER,
    }


@router.get("/nearby/competitors")
async def nearby_competitors(
    latitude:  float,
    longitude: float,
    radius:    int = 500,
    limit:     int = 100,
    db: Session = Depends(get_db),
):
    """Returns nearby reference observations for map marker display."""
    # Snap radius to allowed values
    if radius not in ALLOWED_RADII:
        radius = min(ALLOWED_RADII, key=lambda r: abs(r - radius))

    sql = text("""
        SELECT
            id,
            ST_Y(geom::geometry) AS lat,
            ST_X(geom::geometry) AS lon,
            stability_label
        FROM observations
        WHERE ST_DWithin(
            geom::geography,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
            :radius
        )
        LIMIT :limit
    """)
    rows = db.execute(sql, {
        "lat": latitude, "lon": longitude, "radius": radius, "limit": limit,
    }).mappings().all()

    return {
        "count": len(rows),
        "results": [
            {
                "id":              r["id"],
                "latitude":        float(r["lat"]),
                "longitude":       float(r["lon"]),
                "reference_label": bool(r["stability_label"]),
            }
            for r in rows
        ],
    }
