"""
Retraining service — reproduces the notebook pipeline exactly.

Reads from the `observations` table (same schema as kigali_personal_care_dataset.csv),
engineers the same 5 derived features, runs the same spatial hold-out split
(Kimironko + Remera → train, Kacyiru → test), fits a tuned Random Forest,
computes SHAP values, and overwrites the three artefact files:
  ml/artifacts/rf_pipeline.joblib
  ml/artifacts/shap_explainer.joblib
  ml/artifacts/model_metadata.json

This is called by the admin /retrain endpoint.
"""

import json
import time
from pathlib import Path

import joblib
from joblib import parallel_config
import numpy as np
import pandas as pd
import shap
from scipy.stats import randint
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score, classification_report,
    f1_score, roc_auc_score,
)
from sklearn.model_selection import RandomizedSearchCV, StratifiedKFold
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy.orm import Session

ARTEFACTS_DIR = Path(__file__).resolve().parents[2] / "ml" / "artifacts"

# Feature lists — must stay in sync with model_service.py and the notebook
BASE_FEATURES = [
    "comp_count_300", "comp_count_500", "comp_count_1k",
    "traffic_morning", "traffic_midday", "traffic_evening",
    "dist_transport", "dist_market", "dist_road",
    "pop_density", "road_type",
]
ENGINEERED = [
    "avg_traffic", "traffic_peak_ratio", "comp_gradient",
    "access_score", "market_exposure",
]
FULL_FEATURES = BASE_FEATURES + ENGINEERED
TARGET = "reference_label"

# Cluster IDs — must match the seed data and observation import
CLUSTER_MAP     = {0: "Kimironko", 1: "Remera", 2: "Kacyiru"}
TRAIN_CLUSTERS  = [0, 1]   # Kimironko + Remera
TEST_CLUSTER    = 2         # Kacyiru spatial hold-out

CV = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)


# ── Data loading ──────────────────────────────────────────────────────────────

def load_dataframe(db: Session) -> pd.DataFrame:
    """Loads all observations from the database into a DataFrame."""
    from sqlalchemy import text
    rows = db.execute(text("""
        SELECT
            comp_count_300, comp_count_500, comp_count_1k,
            traffic_morning, traffic_midday, traffic_evening,
            dist_transport, dist_market, dist_road,
            pop_density,
            CASE WHEN road_type THEN 1 ELSE 0 END AS road_type,
            CASE WHEN stability_label THEN 1 ELSE 0 END AS reference_label,
            cluster_id AS cluster
        FROM observations
        WHERE
            comp_count_300  IS NOT NULL AND
            traffic_morning IS NOT NULL AND
            stability_label IS NOT NULL AND
            cluster_id      IS NOT NULL
    """)).mappings().all()

    if not rows:
        raise ValueError("No observations found in the database. Import field data first.")

    df = pd.DataFrame(rows)

    # Cast to correct dtypes to match notebook schema
    int_cols = [
        "comp_count_300", "comp_count_500", "comp_count_1k",
        "traffic_morning", "traffic_midday", "traffic_evening",
        "dist_transport", "dist_market", "dist_road",
        "road_type", "reference_label", "cluster",
    ]
    for col in int_cols:
        df[col] = df[col].astype(int)
    df["pop_density"] = df["pop_density"].astype(float)

    return df


# ── Feature engineering (identical to notebook Cell 18) ──────────────────────

def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["avg_traffic"]        = (df["traffic_morning"] + df["traffic_midday"] + df["traffic_evening"]) / 3
    df["traffic_peak_ratio"] = df["traffic_evening"] / (df["traffic_morning"] + 1)
    df["comp_gradient"]      = df["comp_count_1k"] - df["comp_count_300"]
    df["access_score"]       = (
        (3 - df["dist_transport"]) +
        (3 - df["dist_road"]) +
        (3 - df["dist_market"])
    )
    df["market_exposure"] = df["avg_traffic"] * (3 - df["dist_market"])
    return df


# ── Training pipeline ─────────────────────────────────────────────────────────

def retrain(db: Session) -> dict:
    """
    Full retraining pipeline. Returns a metadata dict on success.
    Raises on failure so the caller can surface the error to the admin UI.
    """
    start = time.time()

    # 1. Load and engineer
    df = load_dataframe(db)
    df = engineer_features(df)

    n_obs      = len(df)
    n_clusters = df["cluster"].nunique()

    if n_clusters < 2:
        raise ValueError(
            f"Retraining requires observations from at least 2 clusters. "
            f"Found {n_clusters}. Import more data first."
        )

    # 2. Spatial hold-out split — identical to notebook Cell 21
    # If Kacyiru data exists use it as the test cluster; otherwise use the
    # last available cluster so the split is always meaningful.
    available_clusters = sorted(df["cluster"].unique().tolist())
    if TEST_CLUSTER in available_clusters and len(available_clusters) >= 2:
        test_cluster    = TEST_CLUSTER
        train_clusters  = [c for c in available_clusters if c != TEST_CLUSTER]
        test_cluster_name = CLUSTER_MAP.get(test_cluster, str(test_cluster))
    else:
        test_cluster      = available_clusters[-1]
        train_clusters    = available_clusters[:-1]
        test_cluster_name = CLUSTER_MAP.get(test_cluster, str(test_cluster))

    train_df = df[df["cluster"].isin(train_clusters)].copy().reset_index(drop=True)
    test_df  = df[df["cluster"] == test_cluster].copy().reset_index(drop=True)

    X_train, y_train = train_df[FULL_FEATURES], train_df[TARGET]
    X_test,  y_test  = test_df[FULL_FEATURES],  test_df[TARGET]

    if len(X_train) < 20:
        raise ValueError(
            f"Training set has only {len(X_train)} observations. "
            f"At least 20 are needed to train reliably."
        )

    # 3. Hyperparameter search — identical to notebook Cell 33
    param_dist = {
        "clf__n_estimators":      randint(100, 300),
        "clf__max_depth":         [6, 8, 10, 12, None],
        "clf__min_samples_leaf":  randint(1, 8),
        "clf__max_features":      ["sqrt", "log2", 0.5, 0.7],
        "clf__min_samples_split": randint(2, 10),
    }

    search_pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", RandomForestClassifier(
            class_weight="balanced", bootstrap=True,
            oob_score=False, random_state=42, n_jobs=1,
        )),
    ])

    search = RandomizedSearchCV(
        search_pipe,
        param_distributions=param_dist,
        n_iter=30,
        cv=CV,
        scoring="roc_auc",
        n_jobs=1,
        random_state=42,
        verbose=1,
        return_train_score=False,
    )
    with parallel_config(backend="sequential"):
        search.fit(X_train, y_train)

    # 4. Final model with best params — identical to notebook Cell 35
    best_params = {k.replace("clf__", ""): v for k, v in search.best_params_.items()}
    best_params.update({
        "class_weight": "balanced",
        "bootstrap":    True,
        "oob_score":    True,
        "random_state": 42,
        "n_jobs":       1,
    })

    rf_pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", RandomForestClassifier(**best_params)),
    ])
    with parallel_config(backend="sequential"):
        rf_pipe.fit(X_train, y_train)
    rf_clf = rf_pipe.named_steps["clf"]

    y_pred_rf = rf_pipe.predict(X_test)
    y_prob_rf = rf_pipe.predict_proba(X_test)[:, 1]

    test_auc = float(roc_auc_score(y_test, y_prob_rf))
    test_f1  = float(f1_score(y_test, y_pred_rf, zero_division=0))
    oob      = float(rf_clf.oob_score_)

    # Enforce minimum performance threshold from research proposal
    if test_auc < 0.70:
        raise ValueError(
            f"Retrained model AUC-ROC = {test_auc:.4f}, below the 0.70 minimum "
            f"threshold. The new artefacts were NOT saved. Check data quality."
        )

    # 5. SHAP — identical to notebook Cell 46
    scaler     = rf_pipe.named_steps["scaler"]
    X_test_s   = pd.DataFrame(scaler.transform(X_test), columns=FULL_FEATURES)
    explainer  = shap.TreeExplainer(rf_clf)
    ev         = explainer.expected_value
    base_val   = float(ev[1]) if hasattr(ev, "__len__") else float(ev)

    # 6. Serialise — identical to notebook Cell 52
    ARTEFACTS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(rf_pipe,   ARTEFACTS_DIR / "rf_pipeline.joblib")
    joblib.dump(explainer, ARTEFACTS_DIR / "shap_explainer.joblib")
    joblib.dump(scaler,    ARTEFACTS_DIR / "scaler.joblib")

    train_cluster_names = [CLUSTER_MAP.get(c, str(c)) for c in train_clusters]

    metadata = {
        "model":               "RandomForestClassifier",
        "best_params":         {k: str(v) for k, v in best_params.items()},
        "features":            FULL_FEATURES,
        "base_features":       BASE_FEATURES,
        "engineered_features": ENGINEERED,
        "target":              TARGET,
        "business_category":   "personal_care_services",
        "clusters_train":      train_cluster_names,
        "cluster_test":        test_cluster_name,
        "n_train":             int(len(X_train)),
        "n_test":              int(len(X_test)),
        "test_auc_roc":        round(test_auc, 4),
        "test_f1":             round(test_f1, 4),
        "oob_score":           round(oob, 4),
        "shap_base_value":     round(base_val, 4),
    }
    with open(ARTEFACTS_DIR / "model_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    # 7. Bust the in-memory model cache in model_service so the new artefacts
    #    are loaded immediately on the next inference call.
    try:
        from app.services import model_service
        model_service._pipeline = None
        model_service._explainer = None
        model_service._metadata  = None
    except Exception:
        pass  # Non-fatal — next restart will pick up the new files

    elapsed = round(time.time() - start, 1)

    return {
        "status":        "ok",
        "n_observations": n_obs,
        "n_train":        int(len(X_train)),
        "n_test":         int(len(X_test)),
        "test_auc_roc":   round(test_auc, 4),
        "test_f1":        round(test_f1, 4),
        "oob_score":      round(oob, 4),
        "elapsed_seconds": elapsed,
        "message": (
            f"Retraining complete in {elapsed}s. "
            f"AUC-ROC={test_auc:.4f}, F1={test_f1:.4f}. "
            f"Artefacts updated."
        ),
    }
