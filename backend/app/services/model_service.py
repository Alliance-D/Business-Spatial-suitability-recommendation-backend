"""
Loads the trained Random Forest pipeline, scaler, and SHAP explainer
produced by the model development notebook, and exposes prediction and
explanation functions to the API layer.
"""

import json
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd

ARTIFACT_DIR  = Path(__file__).resolve().parents[2] / "ml" / "artifacts"
MODEL_PATH    = ARTIFACT_DIR / "rf_pipeline.joblib"
EXPLAINER_PATH = ARTIFACT_DIR / "shap_explainer.joblib"
METADATA_PATH = ARTIFACT_DIR / "model_metadata.json"

_pipeline: Optional[object] = None
_explainer: Optional[object] = None
_metadata: Optional[dict] = None


def load_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = joblib.load(MODEL_PATH)
    return _pipeline


def load_explainer():
    global _explainer
    if _explainer is None:
        _explainer = joblib.load(EXPLAINER_PATH)
    return _explainer


def load_metadata() -> dict:
    global _metadata
    if _metadata is None:
        with open(METADATA_PATH, "r", encoding="utf-8") as f:
            _metadata = json.load(f)
    return _metadata


def build_engineered_features(base_features: dict) -> dict:
    """
    Derives the 5 engineered features from the 11 base spatial features,
    using the same formulas as model notebook Section 4.
    """
    features = dict(base_features)

    morning = float(features["traffic_morning"])
    midday  = float(features["traffic_midday"])
    evening = float(features["traffic_evening"])
    total_traffic = morning + midday + evening

    comp_300 = float(features["comp_count_300"])
    comp_1k  = float(features["comp_count_1k"])

    dist_transport = float(features["dist_transport"])
    dist_market    = float(features["dist_market"])
    dist_road      = float(features["dist_road"])

    features["avg_traffic"]        = total_traffic / 3.0
    features["traffic_peak_ratio"] = evening / (morning + 1.0)
    features["comp_gradient"]      = comp_1k - comp_300
    features["access_score"]       = (3 - dist_transport) + (3 - dist_road) + (3 - dist_market)
    features["market_exposure"]    = features["avg_traffic"] * (3 - dist_market)

    return features


def predict(base_features: dict) -> dict:
    """
    Runs the full inference pipeline: feature engineering -> scaling ->
    Random Forest prediction -> SHAP explanation.

    Returns the predicted probability, label, engineered feature vector,
    and per-feature SHAP contributions for the positive (favourable) class.
    """
    pipeline = load_pipeline()
    metadata = load_metadata()
    explainer = load_explainer()

    features = build_engineered_features(base_features)
    feature_names = metadata["features"]

    X = pd.DataFrame([[features[name] for name in feature_names]], columns=feature_names)

    probability = float(pipeline.predict_proba(X)[0][1])
    prediction = int(pipeline.predict(X)[0])

    # SHAP values on the scaled feature space (TreeExplainer expects the
    # same input the Random Forest step receives)
    scaler = pipeline.named_steps["scaler"]
    X_scaled = pd.DataFrame(scaler.transform(X), columns=feature_names)

    raw_shap = explainer.shap_values(X_scaled)
    if isinstance(raw_shap, np.ndarray) and raw_shap.ndim == 3:
        sv = raw_shap[0, :, 1]
    elif isinstance(raw_shap, list):
        sv = np.array(raw_shap[1])[0]
    else:
        sv = raw_shap[0]

    shap_values = {name: float(val) for name, val in zip(feature_names, sv)}

    return {
        "probability": probability,
        "prediction": prediction,
        "features": features,
        "shap_values": shap_values,
        "shap_base_value": float(metadata.get("shap_base_value", 0.5)),
    }
