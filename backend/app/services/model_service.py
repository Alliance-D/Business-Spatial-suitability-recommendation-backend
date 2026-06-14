from pathlib import Path
import json
import joblib
import pandas as pd

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "ml" / "artifacts"
MODEL_PATH = ARTIFACT_DIR / "rf_pipeline.joblib"
METADATA_PATH = ARTIFACT_DIR / "model_metadata.json"

_model = None
_metadata = None


def load_model():
    global _model
    if _model is None:
        _model = joblib.load(MODEL_PATH)
    return _model


def load_metadata():
    global _metadata
    if _metadata is None:
        with open(METADATA_PATH, "r", encoding="utf-8") as f:
            _metadata = json.load(f)
    return _metadata


def build_engineered_features(base_features: dict) -> dict:
    features = dict(base_features)

    morning = float(features["traffic_morning"])
    midday = float(features["traffic_midday"])
    evening = float(features["traffic_evening"])

    traffic_values = [morning, midday, evening]
    total_traffic = morning + midday + evening

    features["avg_traffic"] = total_traffic / 3.0
    features["traffic_peak_ratio"] = max(traffic_values) / total_traffic if total_traffic > 0 else 0.0

    comp_300 = float(features["comp_count_300"])
    comp_500 = float(features["comp_count_500"])
    comp_1k = float(features["comp_count_1k"])

    features["comp_gradient"] = comp_300 / comp_1k if comp_1k > 0 else 0.0

    dist_transport = float(features["dist_transport"])
    dist_market = float(features["dist_market"])
    dist_road = float(features["dist_road"])

    features["access_score"] = 1.0 / (1.0 + ((dist_transport + dist_road) / 2.0))
    features["market_exposure"] = 1.0 / (1.0 + dist_market)

    return features


def predict_suitability(base_features: dict) -> dict:
    model = load_model()
    metadata = load_metadata()

    features = build_engineered_features(base_features)
    feature_names = metadata["features"]

    X = pd.DataFrame(
        [[features[name] for name in feature_names]],
        columns=feature_names
    )

    prediction = int(model.predict(X)[0])

    probabilities = None
    confidence = None

    if hasattr(model, "predict_proba"):
        probabilities = model.predict_proba(X)[0].tolist()
        confidence = float(max(probabilities))

    label = "strong" if prediction == 1 else "weak"

    return {
        "prediction": prediction,
        "label": label,
        "confidence": confidence,
        "probabilities": probabilities,
        "features": features
    }