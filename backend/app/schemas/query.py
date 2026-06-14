from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class SuitabilityQueryRequest(BaseModel):
    latitude: float = Field(..., description="GPS latitude (WGS84)")
    longitude: float = Field(..., description="GPS longitude (WGS84)")
    business_category: str = Field(..., description="Business category (e.g., 'personal_care')")
    # Analysis radius in meters used for buffer-based aggregations (optional)
    radius_meters: Optional[int] = Field(500, description="Analysis radius in meters (e.g., 500)")

class FactorAssessment(BaseModel):
    name: str
    value: float
    assessment: str  # "low", "moderate", "high"
    shap_value: float

class SuitabilityQueryResponse(BaseModel):
    suitability_score: float = Field(..., description="Overall suitability score 0-1")
    suitability_label: str = Field(..., description="Label: strong/moderate/weak")
    factors: List[FactorAssessment]
    top_positive_factors: List[str]
    top_negative_factors: List[str]
    disclaimer: str

class CategoryResponse(BaseModel):
    categories: List[str]
    subtypes: dict

class ModelStatusResponse(BaseModel):
    version: str
    auc_roc: float
    precision: float
    recall: float
    f1_score: float
    deployed: bool
    created_at: datetime
