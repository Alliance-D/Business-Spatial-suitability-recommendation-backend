"""Pydantic request/response schemas for public API endpoints."""

from pydantic import BaseModel, Field
from typing import List, Optional


class AssessRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90, description="GPS latitude (WGS84)")
    longitude: float = Field(..., ge=-180, le=180, description="GPS longitude (WGS84)")
    business_category: str = Field(
        default="personal_care",
        description="Business category. Only 'personal_care' is supported in this version.",
    )
    radius_meters: Optional[int] = Field(
        default=500, description="Analysis radius in metres (300, 500, or 1000)."
    )


class FactorOut(BaseModel):
    factor: str
    rating: str  # favourable | borderline | unfavourable
    detail: str
    explanation: str
    shap_contribution: float


class AssessResponse(BaseModel):
    suitability_probability: float = Field(..., ge=0, le=1)
    suitability_band: str  # FAVOURABLE | BORDERLINE | UNFAVOURABLE
    factors: List[FactorOut]
    disclaimer: str


class CategoryResponse(BaseModel):
    categories: List[str]


class SchemaResponse(BaseModel):
    base_features: List[str]
    engineered_features: List[str]
    distance_bands: dict
    target: str
    notes: str
