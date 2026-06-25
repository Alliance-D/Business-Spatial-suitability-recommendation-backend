"""
Admin API endpoints — authentication, data import, monitoring.
Production: bcrypt password hashing, httpOnly cookie tokens, structured
logging, failed-login tracking, background retraining.
"""

import io
import logging
import os
import time
from datetime import datetime
from typing import Optional

import bcrypt
import jwt
import pandas as pd
from fastapi import (
    APIRouter, BackgroundTasks, Cookie, Depends, File,
    HTTPException, Header, Request, Response, UploadFile,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.observation import Observation, PredictionLog, ImportLog
from app.services import model_service

logger = logging.getLogger("kigalisite.admin")

router = APIRouter()

# Token expiry: 2 hours for production (was 8 hours)
TOKEN_EXPIRY_SECONDS = 60 * 60 * 2


# ─── Authentication helpers ───────────────────────────────────────────────
def _secret() -> str:
    key = os.environ.get("SECRET_KEY", "")
    if not key or key == "dev-secret-change-in-production":
        logger.critical(
            "SECRET_KEY is not set or is using the insecure default. "
            "Set a proper SECRET_KEY in your .env file."
        )
    return key or "dev-secret-change-in-production"


def _hash_password(plain: str) -> str:
    """Hash a plain-text password with bcrypt."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def _check_password(plain: str, hashed: str) -> bool:
    """Verify a plain-text password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def _get_stored_password() -> str:
    """
    Returns the admin password from environment.
    Supports both plain text (legacy) and bcrypt hash (production).
    If ADMIN_PASSWORD_HASH is set, it takes precedence over ADMIN_PASSWORD.

    To generate a hash for your password:
        python -c "import bcrypt; print(bcrypt.hashpw(b'yourpassword', bcrypt.gensalt()).decode())"
    Then set ADMIN_PASSWORD_HASH=<output> in your .env file.
    """
    hashed = os.environ.get("ADMIN_PASSWORD_HASH", "")
    if hashed:
        return hashed
    # Fall back to plain text if no hash is set — will be compared plainly
    return ""


def _verify_credentials(username: str, password: str) -> bool:
    """Verify admin credentials. Supports both bcrypt hash and plain text."""
    admin_user = os.environ.get("ADMIN_USERNAME", "")
    if not admin_user or username != admin_user:
        return False

    stored_hash = _get_stored_password()
    if stored_hash:
        # Bcrypt comparison
        return _check_password(password, stored_hash)
    else:
        # Plain text fallback (development only — should not be used in production)
        plain = os.environ.get("ADMIN_PASSWORD", "")
        return bool(plain) and password == plain


def _create_token(username: str) -> str:
    expiry = int(time.time()) + TOKEN_EXPIRY_SECONDS
    return jwt.encode(
        {"sub": username, "exp": expiry},
        _secret(),
        algorithm="HS256",
    )


def verify_admin_token(token: Optional[str]) -> bool:
    if not token:
        return False
    try:
        jwt.decode(token, _secret(), algorithms=["HS256"])
        return True
    except jwt.ExpiredSignatureError:
        return False
    except jwt.InvalidTokenError:
        return False


async def admin_required(
    authorization: Optional[str] = Header(None),
    admin_token: Optional[str] = Cookie(None),
):
    """
    Accepts the token either as:
    - Authorization: Bearer <token>  (for API clients / Swagger)
    - admin_token httpOnly cookie    (for the browser admin panel)
    """
    token = None

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif admin_token:
        token = admin_token

    if not verify_admin_token(token):
        raise HTTPException(status_code=401, detail="Admin authentication required")
    return True


# ─── Login / Logout ────────────────────────────────────────────────────────
class AdminLogin(BaseModel):
    username: str
    password: str


@router.post("/login")
async def admin_login(credentials: AdminLogin, request: Request, response: Response):
    """
    Authenticates admin and sets an httpOnly cookie containing the JWT.
    Also returns the token in the response body for API clients.
    """
    ip = request.client.host if request.client else "unknown"

    if not _verify_credentials(credentials.username, credentials.password):
        logger.warning(
            f"Failed admin login attempt | username='{credentials.username}' | ip={ip}"
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = _create_token(credentials.username)
    expires_at = int(time.time()) + TOKEN_EXPIRY_SECONDS

    logger.info(f"Admin login successful | username='{credentials.username}' | ip={ip}")

    # Set httpOnly cookie — not accessible from JavaScript
    response.set_cookie(
        key="admin_token",
        value=token,
        httponly=True,
        secure=os.environ.get("HTTPS_ENABLED", "false").lower() == "true",
        samesite="lax",
        max_age=TOKEN_EXPIRY_SECONDS,
        path="/api/v1/admin",
    )

    return {
        "authenticated": True,
        "token": token,           # kept for API clients / Swagger UI
        "expires_at": expires_at,
        "expires_in_seconds": TOKEN_EXPIRY_SECONDS,
    }


@router.post("/logout")
async def admin_logout(response: Response, _: bool = Depends(admin_required)):
    """Clears the httpOnly admin cookie."""
    response.delete_cookie("admin_token", path="/api/v1/admin")
    logger.info("Admin logout")
    return {"message": "Logged out."}


# ─── Status ────────────────────────────────────────────────────────────────
@router.get("/db/status")
async def db_status(db: Session = Depends(get_db), _: bool = Depends(admin_required)):
    """Database connection status and reference dataset summary."""
    try:
        pg_version      = db.execute(text("SELECT version()")).scalar()
        postgis_version = db.execute(text("SELECT PostGIS_Version()")).scalar()

        row = db.execute(text("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN stability_label THEN 1 ELSE 0 END) AS positive,
                SUM(CASE WHEN NOT stability_label THEN 1 ELSE 0 END) AS negative
            FROM observations
        """)).mappings().first()

        return {
            "status":              "operational",
            "postgres_version":    pg_version,
            "postgis_version":     postgis_version,
            "total_observations":  int(row["total"]    or 0),
            "positive_references": int(row["positive"] or 0),
            "negative_references": int(row["negative"] or 0),
        }
    except Exception as exc:
        logger.error(f"DB status check failed: {exc}")
        # Return 500 — not 200 with error flag
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Database connection failed"},
        )


# ─── Model metrics ─────────────────────────────────────────────────────────
@router.get("/model/metrics")
async def model_metrics(_: bool = Depends(admin_required)):
    """Returns the active model's evaluation metrics from training metadata."""
    try:
        metadata = model_service.load_metadata()
        return {
            "model":          metadata.get("model"),
            "test_auc_roc":   metadata.get("test_auc_roc"),
            "test_f1":        metadata.get("test_f1"),
            "oob_score":      metadata.get("oob_score"),
            "n_train":        metadata.get("n_train"),
            "n_test":         metadata.get("n_test"),
            "clusters_train": metadata.get("clusters_train"),
            "cluster_test":   metadata.get("cluster_test"),
        }
    except FileNotFoundError:
        raise HTTPException(
            status_code=503,
            detail="Model metadata not found. Run training pipeline first.",
        )


# ─── Retrain (background task) ─────────────────────────────────────────────
_retrain_status = {"running": False, "last_result": None, "last_error": None}


def _run_retrain(db_url: str):
    """
    Background retraining function. Runs in a separate thread via
    FastAPI BackgroundTasks so the API remains responsive during training.
    Creates its own database session since it runs outside the request lifecycle.
    """
    from app.db import SessionLocal
    _retrain_status["running"] = True
    _retrain_status["last_result"] = None
    _retrain_status["last_error"] = None
    logger.info("Background retraining started.")

    db = SessionLocal()
    try:
        from app.services.retrain_service import retrain
        result = retrain(db)
        _retrain_status["last_result"] = result
        logger.info(
            f"Retraining complete | AUC-ROC={result.get('test_auc_roc')} "
            f"| F1={result.get('test_f1')} | elapsed={result.get('elapsed_seconds')}s"
        )
    except Exception as exc:
        _retrain_status["last_error"] = str(exc)
        logger.error(f"Retraining failed: {exc}")
    finally:
        db.close()
        _retrain_status["running"] = False


@router.post("/model/retrain")
async def trigger_retrain(
    background_tasks: BackgroundTasks,
    _: bool = Depends(admin_required),
):
    """
    Triggers model retraining as a background task.
    Returns immediately — poll /admin/model/retrain/status to track progress.
    The API remains responsive during retraining (no blocking).
    """
    if _retrain_status["running"]:
        raise HTTPException(
            status_code=409,
            detail="Retraining is already in progress. Check /admin/model/retrain/status.",
        )

    import os
    background_tasks.add_task(_run_retrain, os.environ.get("DATABASE_URL", ""))
    logger.info("Retraining task queued.")

    return {
        "status":  "started",
        "message": "Retraining started in the background. Poll /admin/model/retrain/status for progress.",
    }


@router.get("/model/retrain/status")
async def retrain_status(_: bool = Depends(admin_required)):
    """Returns the current state of any in-progress or completed retraining job."""
    return {
        "running":     _retrain_status["running"],
        "last_result": _retrain_status["last_result"],
        "last_error":  _retrain_status["last_error"],
    }


# ─── Predictions ───────────────────────────────────────────────────────────
@router.get("/predictions/recent")
async def recent_predictions(
    limit: int = 50,
    db:    Session = Depends(get_db),
    _:     bool    = Depends(admin_required),
):
    rows = db.execute(text("""
        SELECT id, latitude, longitude, business_category,
               suitability_score, predicted_label, created_at, ip_address
        FROM prediction_log
        ORDER BY created_at DESC
        LIMIT :limit
    """), {"limit": limit}).mappings().all()

    return {
        "count": len(rows),
        "predictions": [
            {
                "id":                r["id"],
                "latitude":          r["latitude"],
                "longitude":         r["longitude"],
                "business_category": r["business_category"],
                "suitability_score": r["suitability_score"],
                "suitability_band":  (
                    "FAVOURABLE"   if r["suitability_score"] and r["suitability_score"] >= 0.65
                    else "BORDERLINE"   if r["suitability_score"] and r["suitability_score"] >= 0.40
                    else "UNFAVOURABLE" if r["suitability_score"] is not None
                    else "—"
                ),
                "created_at":  r["created_at"].isoformat() if r["created_at"] else None,
                "ip_address":  r["ip_address"],
            }
            for r in rows
        ],
    }


# ─── Observation import ────────────────────────────────────────────────────
REQUIRED_COLUMNS = [
    "latitude", "longitude",
    "comp_count_300", "comp_count_500", "comp_count_1k",
    "traffic_morning", "traffic_midday", "traffic_evening",
    "dist_transport", "dist_market", "dist_road",
    "pop_density", "road_type", "reference_label",
]

DIST_VALID = range(0, 4)   # 0-3 inclusive


def _validate_row(row, idx: int):
    """Validates a single CSV row. Raises ValueError with a clear message on failure."""
    lat = float(row["latitude"])
    lon = float(row["longitude"])
    if not (-90 <= lat <= 90):
        raise ValueError(f"latitude out of range: {lat}")
    if not (-180 <= lon <= 180):
        raise ValueError(f"longitude out of range: {lon}")
    for dist_col in ("dist_transport", "dist_market", "dist_road"):
        val = int(row[dist_col])
        if val not in DIST_VALID:
            raise ValueError(f"{dist_col} must be 0-3, got {val}")
    ref = int(row["reference_label"])
    if ref not in (0, 1):
        raise ValueError(f"reference_label must be 0 or 1, got {ref}")
    road = int(row["road_type"])
    if road not in (0, 1):
        raise ValueError(f"road_type must be 0 or 1, got {road}")


def _row_to_observation(row) -> Observation:
    label = bool(int(row["reference_label"]))
    return Observation(
        geom=f"SRID=4326;POINT({row['longitude']} {row['latitude']})",
        stability_label=label,
        reference_label=label,
        comp_count_300=int(row["comp_count_300"]),
        comp_count_500=int(row["comp_count_500"]),
        comp_count_1k=int(row["comp_count_1k"]),
        traffic_morning=int(row["traffic_morning"]),
        traffic_midday=int(row["traffic_midday"]),
        traffic_evening=int(row["traffic_evening"]),
        dist_transport=int(row["dist_transport"]),
        dist_market=int(row["dist_market"]),
        dist_road=int(row["dist_road"]),
        pop_density=float(row["pop_density"]),
        road_type=bool(int(row["road_type"])),
        cluster_id=int(row["cluster"]) if "cluster" in row and pd.notna(row["cluster"]) else None,
        cluster_name=str(row["cluster_name"]) if "cluster_name" in row and pd.notna(row["cluster_name"]) else None,
    )


class ObservationCreate(BaseModel):
    latitude:       float
    longitude:      float
    comp_count_300: int
    comp_count_500: int
    comp_count_1k:  int
    traffic_morning: int
    traffic_midday:  int
    traffic_evening: int
    dist_transport: int
    dist_market:    int
    dist_road:      int
    pop_density:    float
    road_type:      bool
    reference_label: bool
    cluster:        Optional[int] = None
    cluster_name:   Optional[str] = None


@router.post("/observations/single")
async def add_single_observation(
    obs: ObservationCreate,
    db:  Session = Depends(get_db),
    _:   bool    = Depends(admin_required),
):
    """Adds a single field-collected observation to the reference dataset."""
    try:
        label = obs.reference_label
        new_obs = Observation(
            geom=f"SRID=4326;POINT({obs.longitude} {obs.latitude})",
            stability_label=label,
            reference_label=label,
            comp_count_300=obs.comp_count_300,
            comp_count_500=obs.comp_count_500,
            comp_count_1k=obs.comp_count_1k,
            traffic_morning=obs.traffic_morning,
            traffic_midday=obs.traffic_midday,
            traffic_evening=obs.traffic_evening,
            dist_transport=obs.dist_transport,
            dist_market=obs.dist_market,
            dist_road=obs.dist_road,
            pop_density=obs.pop_density,
            road_type=obs.road_type,
            cluster_id=obs.cluster,
            cluster_name=obs.cluster_name,
        )
        db.add(new_obs)
        db.commit()
        db.refresh(new_obs)
        logger.info(f"Single observation added | id={new_obs.id}")
        return {"id": new_obs.id, "message": "Observation added successfully."}
    except Exception as exc:
        db.rollback()
        logger.error(f"Single observation insert failed: {exc}")
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/observations/bulk")
async def bulk_observations(
    file: UploadFile = File(...),
    db:   Session    = Depends(get_db),
    _:    bool       = Depends(admin_required),
):
    """
    Bulk import observations from a CSV matching the dataset schema.
    After import, use recompute-spatial to update spatial features,
    then retrain the model.
    """
    filename = getattr(file, "filename", "upload.csv")

    # File type check
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted.")

    contents = await file.read()

    # Size limit: 10 MB
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File exceeds 10 MB limit.")

    try:
        df = pd.read_csv(io.BytesIO(contents))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {exc}")

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"CSV is missing required columns: {', '.join(missing)}",
        )

    added_count = 0
    errors = []
    for idx, row in df.iterrows():
        try:
            _validate_row(row, idx)
            db.add(_row_to_observation(row))
            added_count += 1
        except Exception as row_err:
            errors.append(f"row {idx}: {row_err}")

    db.commit()

    try:
        db.add(ImportLog(
            filename=filename,
            imported_count=added_count,
            errors="; ".join(errors) if errors else None,
        ))
        db.commit()
    except Exception:
        db.rollback()

    logger.info(f"Bulk import | file={filename} | imported={added_count} | errors={len(errors)}")
    return {
        "imported": added_count,
        "errors":   errors,
        "message":  (
            f"Imported {added_count} observations. "
            "Use Recompute Spatial Features, then Retrain to apply the new data."
        ),
    }


@router.get("/import/logs")
async def import_logs(
    limit: int = 50,
    db:    Session = Depends(get_db),
    _:     bool    = Depends(admin_required),
):
    rows = db.query(ImportLog).order_by(ImportLog.created_at.desc()).limit(limit).all()
    return {
        "count": len(rows),
        "logs": [
            {
                "id":             r.id,
                "filename":       r.filename,
                "imported_count": r.imported_count,
                "errors":         r.errors,
                "created_at":     r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.post("/observations/recompute-spatial")
async def recompute_spatial_features(
    db: Session = Depends(get_db),
    _:  bool    = Depends(admin_required),
):
    """
    Recomputes comp_count_300/500/1k and dist_transport/market/road for every
    observation via PostGIS. Run after a bulk import.
    """
    try:
        db.execute(text("""
            UPDATE observations o SET
                comp_count_300 = sub.c300,
                comp_count_500 = sub.c500,
                comp_count_1k  = sub.c1k
            FROM (
                SELECT a.id,
                    COUNT(*) FILTER (WHERE ST_DWithin(a.geom::geography, b.geom::geography, 300)  AND a.id <> b.id) AS c300,
                    COUNT(*) FILTER (WHERE ST_DWithin(a.geom::geography, b.geom::geography, 500)  AND a.id <> b.id) AS c500,
                    COUNT(*) FILTER (WHERE ST_DWithin(a.geom::geography, b.geom::geography, 1000) AND a.id <> b.id) AS c1k
                FROM observations a
                CROSS JOIN observations b
                GROUP BY a.id
            ) sub
            WHERE o.id = sub.id
        """))

        for col, table in [
            ("dist_market",    "poi_market"),
            ("dist_transport", "poi_transport"),
            ("dist_road",      "poi_road"),
        ]:
            db.execute(text(f"""
                UPDATE observations o SET {col} = sub.band
                FROM (
                    SELECT o2.id,
                        CASE
                            WHEN d.dist_m < 50  THEN 0
                            WHEN d.dist_m < 150 THEN 1
                            WHEN d.dist_m < 400 THEN 2
                            ELSE 3
                        END AS band
                    FROM observations o2
                    CROSS JOIN LATERAL (
                        SELECT MIN(ST_Distance(o2.geom::geography, p.geom::geography)) AS dist_m
                        FROM {table} p
                    ) d
                ) sub
                WHERE o.id = sub.id
            """))

        db.commit()
        logger.info("Spatial features recomputed for all observations.")
        return {"status": "ok", "message": "Spatial features recomputed for all observations."}
    except Exception as exc:
        db.rollback()
        logger.error(f"Spatial recompute failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
