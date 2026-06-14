from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ARRAY, LargeBinary
from geoalchemy2 import Geometry
from datetime import datetime
from app.db import Base

class Observation(Base):
    """Field-collected business observation"""
    __tablename__ = "observations"

    id = Column(Integer, primary_key=True, index=True)
    geom = Column(Geometry(geometry_type="Point", srid=4326), nullable=False)
    biz_category = Column(String, index=True)
    biz_subtype = Column(String, index=True)
    
    # Spatial features
    comp_count_300 = Column(Integer)
    comp_count_500 = Column(Integer)
    comp_count_1k = Column(Integer)
    
    # Traffic counts
    traffic_morning = Column(Integer)
    traffic_midday = Column(Integer)
    traffic_evening = Column(Integer)
    
    # Distance categories
    dist_transport = Column(Integer)  # 1-4 scale
    dist_market = Column(Integer)     # 1-4 scale
    dist_road = Column(Integer)       # 1-4 scale
    
    # Population and infrastructure
    pop_density = Column(Float)
    road_type = Column(Boolean)  # True = tarmac, False = unpaved
    
    # Target label
    stability_label = Column(Boolean, nullable=False)
    
    # Cluster reference
    cluster_id = Column(Integer, index=True)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ModelArtefact(Base):
    """Serialized ML model and metadata"""
    __tablename__ = "model_artefact"

    id = Column(Integer, primary_key=True, index=True)
    version = Column(String, unique=True, index=True)
    model_bytes = Column(LargeBinary, nullable=False)
    
    # Performance metrics
    auc_roc = Column(Float)
    precision = Column(Float)
    recall = Column(Float)
    f1_score = Column(Float)
    
    # Metadata
    feature_names = Column(ARRAY(String))
    deployed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PredictionLog(Base):
    """Log of user queries for analysis"""
    __tablename__ = "prediction_log"

    id = Column(Integer, primary_key=True, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    business_category = Column(String)
    suitability_score = Column(Float)
    predicted_label = Column(Boolean)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    ip_address = Column(String, nullable=True)


class ImportLog(Base):
    """Records CSV import runs and results"""
    __tablename__ = "import_log"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)
    imported_count = Column(Integer)
    errors = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
