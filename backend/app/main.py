from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import query, admin
from app.db import engine
import app.models as models

try:
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
        conn.commit()
        print("PostGIS extension enabled")
except Exception as e:
    print(f"PostGIS extension setup failed: {e}")

# Create database tables
models.Base.metadata.create_all(bind=engine)

# Setup spatial functions and views
try:
    from app.spatial_setup import create_spatial_functions
    create_spatial_functions()
except Exception as e:
    print(f"Note: Spatial setup (may already exist): {e}")

app = FastAPI(
    title="Kigali Spatial Suitability API",
    description="Spatial suitability assessment for personal care businesses in Kigali",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(query.router, prefix="/api/v1", tags=["public"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])

@app.get("/")
def read_root():
    return {
        "message": "Kigali Spatial Suitability System API",
        "docs": "/docs"
    }

@app.get("/health")
def health_check():
    return {"status": "healthy"}
