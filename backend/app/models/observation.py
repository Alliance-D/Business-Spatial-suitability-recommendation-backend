"""
SQLAlchemy models aligned to the actual database table structure.

The observations table was originally created with a different schema than
the current model. This file matches what is actually in the database.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text
from geoalchemy2 import Geometry
from app.db import Base


class Observation(Base):
    """
    Field-collected personal care service location.
    Matches the actual observations table in the database exactly.
    """
    __tablename__ = "observations"

    id           = Column(Integer, primary_key=True, index=True)
    geom         = Column(Geometry(geometry_type="POINT", srid=4326), nullable=False)

    # Original schema columns (created with the table)
    biz_category = Column(String, nullable=True)
    biz_subtype  = Column(String, nullable=True)

    # Spatial features
    comp_count_300 = Column(Integer)
    comp_count_500 = Column(Integer)
    comp_count_1k  = Column(Integer)

    # Field observations
    traffic_morning = Column(Integer)
    traffic_midday  = Column(Integer)
    traffic_evening = Column(Integer)
    dist_transport  = Column(Integer)
    dist_market     = Column(Integer)
    dist_road       = Column(Integer)
    pop_density     = Column(Float)
    road_type       = Column(Boolean)

    # The original label column — NOT NULL in the actual table
    # True = positive spatial reference, False = negative
    stability_label = Column(Boolean, nullable=False)

    # Cluster assignment
    cluster_id   = Column(Integer, index=True)
    cluster_name = Column(String, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # reference_label was added later via migration — kept for compatibility
    # It is a duplicate of stability_label; seed_data populates both.
    reference_label = Column(Boolean, nullable=False, default=False)


class POIMarket(Base):
    """Market and commercial anchor points."""
    __tablename__ = "poi_market"
    id   = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    geom = Column(Geometry(geometry_type="POINT", srid=4326), nullable=False)


class POITransport(Base):
    """Bus stops / moto-taxi stands."""
    __tablename__ = "poi_transport"
    id   = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    geom = Column(Geometry(geometry_type="POINT", srid=4326), nullable=False)


class POIRoad(Base):
    """Major road centrelines."""
    __tablename__ = "poi_road"
    id   = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    geom = Column(Geometry(geometry_type="LINESTRING", srid=4326), nullable=False)


class ModelArtefact(Base):
    """Metadata for a trained model version."""
    __tablename__ = "model_artefact"
    id           = Column(Integer, primary_key=True, index=True)
    version      = Column(String, unique=True, index=True)
    model_type   = Column(String)
    auc_roc      = Column(Float)
    f1_score     = Column(Float)
    oob_score    = Column(Float)
    n_train      = Column(Integer)
    n_test       = Column(Integer)
    deployed     = Column(Boolean, default=False)
    created_at   = Column(DateTime, default=datetime.utcnow)


class PredictionLog(Base):
    """
    Log of assessment queries served by the API.
    Matches the actual prediction_log table in the database.
    """
    __tablename__ = "prediction_log"

    id                = Column(Integer, primary_key=True, index=True)
    latitude          = Column(Float, nullable=False)
    longitude         = Column(Float, nullable=False)
    business_category = Column(String)        # actual column name in DB
    suitability_score = Column(Float)
    predicted_label   = Column(Boolean)       # actual column name in DB
    created_at        = Column(DateTime, default=datetime.utcnow, index=True)
    ip_address        = Column(String, nullable=True)


class ImportLog(Base):
    """Records CSV import runs and results."""
    __tablename__ = "import_log"
    id             = Column(Integer, primary_key=True, index=True)
    filename       = Column(String)
    imported_count = Column(Integer)
    errors         = Column(Text, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow, index=True)
