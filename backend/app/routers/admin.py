from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Header
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db import get_db
from app.models.observation import Observation, ModelArtefact, PredictionLog, ImportLog
import os
import jwt
import time
from typing import Optional
from pydantic import BaseModel
from typing import Optional
import io
import pandas as pd

router = APIRouter()

def verify_admin_token(token: Optional[str]) -> bool:
    if not token:
        return False
    secret = os.environ.get('SECRET_KEY', 'dev-secret')
    try:
        payload = jwt.decode(token, secret, algorithms=['HS256'])
        # token valid if decode succeeds and exp is in the future (PyJWT checks exp)
        return True
    except jwt.ExpiredSignatureError:
        return False
    except Exception:
        return False


async def admin_required(authorization: Optional[str] = Header(None)):
    # Accept Authorization: Bearer <token>
    token = None
    if authorization and authorization.lower().startswith('bearer '):
        token = authorization.split(' ', 1)[1].strip()
    if not verify_admin_token(token):
        raise HTTPException(status_code=401, detail="Admin authentication required")
    return True

class ObservationCreate(BaseModel):
    latitude: float
    longitude: float
    biz_category: int
    comp_count_300: int
    comp_count_500: int
    comp_count_1k: int
    traffic_morning: int
    traffic_midday: int
    traffic_evening: int
    dist_transport: int
    dist_market: int
    dist_road: int
    pop_density: float
    road_type: bool
    stability_label: bool
    cluster_id: Optional[int] = None

@router.post("/observations/single")
async def add_single_observation(
    obs: ObservationCreate,
    db: Session = Depends(get_db),
    _: bool = Depends(admin_required)
):
    """
    Add a single observation record.
    Example: POST /api/v1/admin/observations/single
    """
    try:
        new_obs = Observation(
            geom=f"SRID=4326;POINT({obs.longitude} {obs.latitude})",
            biz_category=str(obs.biz_category),
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
            stability_label=obs.stability_label,
            cluster_id=obs.cluster_id
        )
        db.add(new_obs)
        db.commit()
        db.refresh(new_obs)
        return {"id": new_obs.id, "message": "Observation added successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/observations/bulk")
async def bulk_observations(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: bool = Depends(admin_required)
):
    """
    Bulk import observations from CSV.
    CSV columns: latitude, longitude, biz_category, comp_count_300, ..., stability_label
    """
    filename = getattr(file, 'filename', 'upload.csv')
    try:
        contents = await file.read()
        df = pd.read_csv(io.BytesIO(contents))

        added_count = 0
        errors = []
        for idx, row in df.iterrows():
            try:
                new_obs = Observation(
                    geom=f"SRID=4326;POINT({row['longitude']} {row['latitude']})",
                    biz_category=str(int(row['biz_category'])),
                    comp_count_300=int(row['comp_count_300']),
                    comp_count_500=int(row['comp_count_500']),
                    comp_count_1k=int(row['comp_count_1k']),
                    traffic_morning=int(row['traffic_morning']),
                    traffic_midday=int(row['traffic_midday']),
                    traffic_evening=int(row['traffic_evening']),
                    dist_transport=int(row['dist_transport']),
                    dist_market=int(row['dist_market']),
                    dist_road=int(row['dist_road']),
                    pop_density=float(row['pop_density']),
                    road_type=bool(int(row['road_type'])),
                    stability_label=bool(int(row['stability_label'])),
                    cluster_id=int(row['cluster']) if 'cluster' in row else None
                )
                db.add(new_obs)
                added_count += 1
            except Exception as row_err:
                errors.append(f"row {idx}: {str(row_err)}")

        db.commit()

        # Record import log
        try:
            log = ImportLog(filename=filename, imported_count=added_count, errors='; '.join(errors) if errors else None)
            db.add(log)
            db.commit()
        except Exception:
            db.rollback()

        return {"imported": added_count, "errors": errors, "message": f"Imported {added_count} observations"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/observations/count")
async def observation_count(db: Session = Depends(get_db)):
    """Get total count of observations in database."""
    count = db.query(Observation).count()
    return {"total_observations": count}


@router.get('/import/logs')
async def import_logs(limit: int = 50, db: Session = Depends(get_db), _: bool = Depends(admin_required)):
    """Return recent import run logs (admin only)."""
    try:
        q = db.query(ImportLog).order_by(ImportLog.created_at.desc()).limit(limit).all()
        return {
            'count': len(q),
            'logs': [
                {
                    'id': r.id,
                    'filename': r.filename,
                    'imported_count': r.imported_count,
                    'errors': r.errors,
                    'created_at': r.created_at.isoformat() if r.created_at else None
                }
                for r in q
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/predictions/recent")
async def recent_predictions(limit: int = 100, db: Session = Depends(get_db), _: bool = Depends(admin_required)):
    """Return recent prediction logs for reporting/export."""
    try:
        q = db.query(PredictionLog).order_by(PredictionLog.created_at.desc()).limit(limit).all()
        result = [
            {
                "id": r.id,
                "latitude": r.latitude,
                "longitude": r.longitude,
                "business_category": r.business_category,
                "suitability_score": r.suitability_score,
                "predicted_label": r.predicted_label,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "ip_address": r.ip_address,
            }
            for r in q
        ]
        return {"count": len(result), "predictions": result}
    except Exception as e:
        # Log error server-side and return safe message
        return HTTPException(status_code=500, detail="Failed to fetch recent predictions: " + str(e))


class AdminLogin(BaseModel):
    username: str
    password: str


@router.post('/login')
async def admin_login(credentials: AdminLogin):
    """Simple admin login that validates against environment variables.
    Note: this is a minimal prototype for local/dev use only.
    """
    admin_user = os.environ.get('ADMIN_USERNAME', 'admin')
    admin_pass = os.environ.get('ADMIN_PASSWORD', 'admin')
    if credentials.username == admin_user and credentials.password == admin_pass:
        # issue JWT token
        secret = os.environ.get('SECRET_KEY', 'dev-secret')
        expiry = int(time.time()) + 60 * 60 * 8  # 8 hours
        payload = {"sub": credentials.username, "exp": expiry}
        token = jwt.encode(payload, secret, algorithm='HS256')
        return {"authenticated": True, "token": token, "expires_at": expiry}
    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.post("/retrain")
async def trigger_retrain(
    db: Session = Depends(get_db)
):
    """
    Trigger model retraining (placeholder).
    In production, this would trigger a background task or external service.
    """
    return {
        "message": "Retrain pipeline triggered",
        "status": "queued",
        "note": "Full ML pipeline integration coming soon"
    }

@router.get("/model/status")
async def model_status(db: Session = Depends(get_db)):
    """Get current model metadata and performance metrics."""
    try:
        # Get the most recently deployed model
        deployed = db.query(ModelArtefact).filter(
            ModelArtefact.deployed == True
        ).order_by(ModelArtefact.created_at.desc()).first()
        
        if not deployed:
            return {"deployed_model": None, "message": "No deployed model found"}
        
        return {
            "version": deployed.version,
            "auc_roc": deployed.auc_roc,
            "precision": deployed.precision,
            "recall": deployed.recall,
            "f1_score": deployed.f1_score,
            "deployed": deployed.deployed,
            "created_at": deployed.created_at.isoformat() if deployed.created_at else None
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/db/status")
async def db_status(db: Session = Depends(get_db)):
    """Get database and PostGIS version info."""
    try:
        pg_version = db.execute(text("SELECT version()")).scalar()
        postgis_version = db.execute(text("SELECT PostGIS_Version()")).scalar()
        obs_count = db.execute(text("SELECT COUNT(*) FROM observations")).scalar()
        
        return {
            "postgres_version": pg_version,
            "postgis_version": postgis_version,
            "observations_count": obs_count,
            "status": "operational"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
