"""
Kigali Spatial Suitability System — FastAPI application entry point.
Production configuration: restricted CORS, rate limiting, structured logging.
"""
from dotenv import load_dotenv
load_dotenv()

import logging
import logging.config
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from app.routers import query, admin
from app.db import engine
import app.models as models

# ── Logging configuration ──────────────────────────────────────────────────
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        "kigalisite": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn.error": {"level": "INFO"},
        "uvicorn.access": {"level": "INFO"},
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
}
logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("kigalisite")

# ── Rate limiter ───────────────────────────────────────────────────────────
# Keyed by IP address. The assess endpoint is limited to 30 requests/minute
# to prevent ML inference flooding. Admin endpoints are not rate-limited
# because they require a valid JWT which already limits access.
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

# ── Database startup ───────────────────────────────────────────────────────
try:
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
        conn.commit()
        logger.info("PostGIS extension enabled.")
except Exception as e:
    logger.warning(f"PostGIS extension setup: {e}")

try:
    models.Base.metadata.create_all(bind=engine)
    logger.info("Database tables ready.")
except Exception as e:
    logger.error(f"Table creation failed: {e}")

try:
    from app.spatial_setup import create_spatial_functions
    create_spatial_functions()
except Exception as e:
    logger.warning(f"Spatial setup (may already exist): {e}")

# ── App ────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Kigali Spatial Suitability API",
    description="Spatial suitability assessment for personal care services in Kigali",
    version="1.0.0",
)

# Attach rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ───────────────────────────────────────────────────────────────────
# Reads allowed origins from environment variable ALLOWED_ORIGINS
# (comma-separated). Falls back to localhost origins for development only.
import os
_raw_origins = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost,http://localhost:5173,http://localhost:3000,http://127.0.0.1,https://spatial-suitability-frontend.onrender.com"
)
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]
logger.info(f"CORS allowed origins: {ALLOWED_ORIGINS}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ── Routers ────────────────────────────────────────────────────────────────
app.include_router(query.router, prefix="/api/v1",       tags=["public"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])


@app.get("/")
def read_root():
    return {
        "message": "Kigali Spatial Suitability System API",
        "docs":    "/docs",
        "version": "1.0.0",
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}
