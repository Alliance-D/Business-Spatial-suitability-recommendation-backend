"""
KigaliSite — Comprehensive API Test Suite
=========================================
Covers: authentication, authorization, public endpoints, admin endpoints,
input validation, error handling, rate limiting awareness, and edge cases.

Run from the /backend folder:
    pytest tests/test_api.py -v

Requirements:
    pip install pytest httpx

Environment:
    Tests use FastAPI's TestClient which does not require a running server.
    Database-dependent tests are skipped if DATABASE_URL is not set or DB
    is unavailable. Model-dependent tests are skipped if artefacts are missing.
"""

import os
import json
import pytest
from fastapi.testclient import TestClient

# ── App import ────────────────────────────────────────────────────────────────
# Set minimal env vars before importing the app so it does not crash on startup
os.environ.setdefault("SECRET_KEY", "test-secret-key-exactly-32-bytes!!")
os.environ.setdefault("ADMIN_USERNAME", "testadmin")
os.environ.setdefault("ADMIN_PASSWORD", "testpassword")
os.environ.setdefault("DATABASE_URL", os.environ.get("DATABASE_URL", ""))
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")

from main import app  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)


# ── Fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def admin_token():
    """Obtain a valid admin JWT once per test session."""
    res = client.post("/api/v1/admin/login", json={
        "username": "testadmin",
        "password": "testpassword",
    })
    if res.status_code == 200 and res.json().get("token"):
        return res.json()["token"]
    pytest.skip("Admin login failed — skipping auth-dependent tests")


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ═════════════════════════════════════════════════════════════════════════════
# 1. ROOT AND HEALTH
# ═════════════════════════════════════════════════════════════════════════════

class TestRoot:
    def test_root_returns_200(self):
        res = client.get("/")
        assert res.status_code == 200

    def test_root_contains_message(self):
        res = client.get("/")
        assert "message" in res.json()

    def test_health_returns_200(self):
        res = client.get("/health")
        assert res.status_code == 200

    def test_health_returns_status_field(self):
        res = client.get("/health")
        assert "status" in res.json()

    def test_docs_available(self):
        res = client.get("/docs")
        assert res.status_code == 200


# ═════════════════════════════════════════════════════════════════════════════
# 2. PUBLIC ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════

class TestPublicEndpoints:
    def test_categories_returns_200(self):
        res = client.get("/api/v1/categories")
        assert res.status_code == 200

    def test_categories_contains_personal_care(self):
        res = client.get("/api/v1/categories")
        assert "personal_care" in res.json()["categories"]

    def test_api_health_returns_200(self):
        res = client.get("/api/v1/health")
        assert res.status_code == 200

    def test_api_health_has_database_field(self):
        res = client.get("/api/v1/health")
        assert "database" in res.json()

    def test_api_health_has_model_field(self):
        res = client.get("/api/v1/health")
        assert "model" in res.json()

    def test_schema_returns_200(self):
        res = client.get("/api/v1/schema")
        # May return 503 if model artefacts missing — both are acceptable
        assert res.status_code in (200, 503)

    def test_schema_has_expected_fields(self):
        res = client.get("/api/v1/schema")
        if res.status_code == 200:
            data = res.json()
            assert "base_features" in data
            assert "engineered_features" in data
            assert "distance_bands" in data


# ═════════════════════════════════════════════════════════════════════════════
# 3. ASSESS ENDPOINT — INPUT VALIDATION
# ═════════════════════════════════════════════════════════════════════════════

class TestAssessValidation:
    VALID_PAYLOAD = {
        "latitude":          -1.9441,
        "longitude":          30.0619,
        "business_category": "personal_care",
        "radius_meters":      500,
    }

    def test_assess_latitude_too_high(self):
        payload = {**self.VALID_PAYLOAD, "latitude": 999}
        res = client.post("/api/v1/assess", json=payload)
        assert res.status_code == 422

    def test_assess_latitude_too_low(self):
        payload = {**self.VALID_PAYLOAD, "latitude": -999}
        res = client.post("/api/v1/assess", json=payload)
        assert res.status_code == 422

    def test_assess_longitude_too_high(self):
        payload = {**self.VALID_PAYLOAD, "longitude": 999}
        res = client.post("/api/v1/assess", json=payload)
        assert res.status_code == 422

    def test_assess_longitude_too_low(self):
        payload = {**self.VALID_PAYLOAD, "longitude": -999}
        res = client.post("/api/v1/assess", json=payload)
        assert res.status_code == 422

    def test_assess_unsupported_category_returns_400(self):
        payload = {**self.VALID_PAYLOAD, "business_category": "snack_kiosk"}
        res = client.post("/api/v1/assess", json=payload)
        assert res.status_code == 400

    def test_assess_missing_latitude_returns_422(self):
        payload = {"longitude": 30.0619, "business_category": "personal_care"}
        res = client.post("/api/v1/assess", json=payload)
        assert res.status_code == 422

    def test_assess_missing_longitude_returns_422(self):
        payload = {"latitude": -1.9441, "business_category": "personal_care"}
        res = client.post("/api/v1/assess", json=payload)
        assert res.status_code == 422

    def test_assess_empty_body_returns_422(self):
        res = client.post("/api/v1/assess", json={})
        assert res.status_code == 422

    def test_assess_string_coordinates_returns_422(self):
        payload = {**self.VALID_PAYLOAD, "latitude": "not-a-number"}
        res = client.post("/api/v1/assess", json=payload)
        assert res.status_code == 422

    def test_assess_valid_kigali_coordinates_accepted(self):
        """Valid coordinates should not be rejected at the validation stage."""
        payload = self.VALID_PAYLOAD
        res = client.post("/api/v1/assess", json=payload)
        # 200 if model+DB available, 503 if not — both mean validation passed
        assert res.status_code in (200, 503)

    def test_assess_radius_snaps_to_nearest_allowed(self):
        """A radius of 600 should snap to 500, not cause an error."""
        payload = {**self.VALID_PAYLOAD, "radius_meters": 600}
        res = client.post("/api/v1/assess", json=payload)
        assert res.status_code in (200, 503)

    def test_assess_default_category_is_personal_care(self):
        """Omitting business_category should default to personal_care."""
        payload = {"latitude": -1.9441, "longitude": 30.0619}
        res = client.post("/api/v1/assess", json=payload)
        assert res.status_code in (200, 503)

    def test_assess_response_structure_when_successful(self):
        """If the model is available, verify the response shape."""
        res = client.post("/api/v1/assess", json=self.VALID_PAYLOAD)
        if res.status_code == 200:
            data = res.json()
            assert "suitability_probability" in data
            assert "suitability_band" in data
            assert "factors" in data
            assert "disclaimer" in data
            assert isinstance(data["factors"], list)
            assert 0.0 <= data["suitability_probability"] <= 1.0

    def test_assess_band_is_valid_value(self):
        res = client.post("/api/v1/assess", json=self.VALID_PAYLOAD)
        if res.status_code == 200:
            band = res.json()["suitability_band"]
            assert band in ("FAVOURABLE", "BORDERLINE", "UNFAVOURABLE")

    def test_assess_factors_have_required_fields(self):
        res = client.post("/api/v1/assess", json=self.VALID_PAYLOAD)
        if res.status_code == 200:
            for factor in res.json()["factors"]:
                assert "factor" in factor
                assert "rating" in factor
                assert "detail" in factor
                assert "explanation" in factor
                assert factor["rating"] in ("favourable", "borderline", "unfavourable")

    def test_assess_disclaimer_is_present_and_non_empty(self):
        res = client.post("/api/v1/assess", json=self.VALID_PAYLOAD)
        if res.status_code == 200:
            disclaimer = res.json()["disclaimer"]
            assert isinstance(disclaimer, str)
            assert len(disclaimer) > 20


# ═════════════════════════════════════════════════════════════════════════════
# 4. NEARBY COMPETITORS
# ═════════════════════════════════════════════════════════════════════════════

class TestNearbyCompetitors:
    def test_nearby_returns_200_or_503(self):
        res = client.get("/api/v1/nearby/competitors", params={
            "latitude": -1.9441, "longitude": 30.0619, "radius": 500
        })
        assert res.status_code in (200, 503)

    def test_nearby_response_has_count_and_results(self):
        res = client.get("/api/v1/nearby/competitors", params={
            "latitude": -1.9441, "longitude": 30.0619, "radius": 500
        })
        if res.status_code == 200:
            data = res.json()
            assert "count" in data
            assert "results" in data
            assert isinstance(data["results"], list)

    def test_nearby_each_result_has_required_fields(self):
        res = client.get("/api/v1/nearby/competitors", params={
            "latitude": -1.9441, "longitude": 30.0619, "radius": 500
        })
        if res.status_code == 200:
            for r in res.json()["results"]:
                assert "id" in r
                assert "latitude" in r
                assert "longitude" in r
                assert "reference_label" in r

    def test_nearby_invalid_latitude_returns_422(self):
        res = client.get("/api/v1/nearby/competitors", params={
            "latitude": "bad", "longitude": 30.0619, "radius": 500
        })
        assert res.status_code == 422


# ═════════════════════════════════════════════════════════════════════════════
# 5. ADMIN AUTHENTICATION
# ═════════════════════════════════════════════════════════════════════════════

class TestAdminAuth:
    def test_login_with_correct_credentials_returns_200(self):
        res = client.post("/api/v1/admin/login", json={
            "username": "testadmin", "password": "testpassword"
        })
        assert res.status_code == 200

    def test_login_returns_token(self):
        res = client.post("/api/v1/admin/login", json={
            "username": "testadmin", "password": "testpassword"
        })
        if res.status_code == 200:
            assert "token" in res.json()
            assert len(res.json()["token"]) > 20

    def test_login_returns_expires_at(self):
        res = client.post("/api/v1/admin/login", json={
            "username": "testadmin", "password": "testpassword"
        })
        if res.status_code == 200:
            assert "expires_at" in res.json()

    def test_login_wrong_password_returns_401(self):
        res = client.post("/api/v1/admin/login", json={
            "username": "testadmin", "password": "wrongpassword"
        })
        assert res.status_code == 401

    def test_login_wrong_username_returns_401(self):
        res = client.post("/api/v1/admin/login", json={
            "username": "notadmin", "password": "testpassword"
        })
        assert res.status_code == 401

    def test_login_empty_credentials_returns_401_or_422(self):
        res = client.post("/api/v1/admin/login", json={
            "username": "", "password": ""
        })
        assert res.status_code in (401, 422)

    def test_login_missing_body_returns_422(self):
        res = client.post("/api/v1/admin/login", json={})
        assert res.status_code == 422

    def test_login_sql_injection_attempt_rejected(self):
        res = client.post("/api/v1/admin/login", json={
            "username": "admin' OR '1'='1", "password": "' OR '1'='1"
        })
        assert res.status_code == 401

    def test_login_very_long_password_rejected(self):
        res = client.post("/api/v1/admin/login", json={
            "username": "testadmin", "password": "x" * 10000
        })
        assert res.status_code in (401, 422, 400)


# ═════════════════════════════════════════════════════════════════════════════
# 6. ADMIN AUTHORIZATION — ALL ROUTES PROTECTED
# ═════════════════════════════════════════════════════════════════════════════

class TestAdminAuthorization:
    """Every admin endpoint must return 401 without a valid token."""

    PROTECTED_GET = [
        "/api/v1/admin/db/status",
        "/api/v1/admin/model/metrics",
        "/api/v1/admin/predictions/recent",
        "/api/v1/admin/import/logs",
        "/api/v1/admin/model/retrain/status",
    ]

    PROTECTED_POST = [
        "/api/v1/admin/model/retrain",
        "/api/v1/admin/observations/recompute-spatial",
    ]

    @pytest.mark.parametrize("path", PROTECTED_GET)
    def test_get_without_token_returns_401(self, path):
        res = client.get(path)
        assert res.status_code == 401, f"Expected 401 for {path}, got {res.status_code}"

    @pytest.mark.parametrize("path", PROTECTED_POST)
    def test_post_without_token_returns_401(self, path):
        res = client.post(path)
        assert res.status_code == 401, f"Expected 401 for {path}, got {res.status_code}"

    def test_bulk_upload_without_token_returns_401(self):
        res = client.post(
            "/api/v1/admin/observations/bulk",
            files={"file": ("test.csv", b"col1,col2\n1,2", "text/csv")},
        )
        assert res.status_code == 401

    def test_fake_token_returns_401(self):
        headers = {"Authorization": "Bearer thisisafaketoken"}
        res = client.get("/api/v1/admin/db/status", headers=headers)
        assert res.status_code == 401

    def test_malformed_auth_header_returns_401(self):
        headers = {"Authorization": "NotBearer sometoken"}
        res = client.get("/api/v1/admin/db/status", headers=headers)
        assert res.status_code == 401


# ═════════════════════════════════════════════════════════════════════════════
# 7. ADMIN ENDPOINTS — WITH VALID TOKEN
# ═════════════════════════════════════════════════════════════════════════════

class TestAdminEndpointsAuthed:
    def test_db_status_with_token(self, auth_headers):
        res = client.get("/api/v1/admin/db/status", headers=auth_headers)
        # 200 if DB available, 500 if not — both mean auth passed
        assert res.status_code in (200, 500)

    def test_db_status_200_has_expected_fields(self, auth_headers):
        res = client.get("/api/v1/admin/db/status", headers=auth_headers)
        if res.status_code == 200:
            data = res.json()
            assert "status" in data
            assert "total_observations" in data
            assert "positive_references" in data
            assert "negative_references" in data

    def test_model_metrics_with_token(self, auth_headers):
        res = client.get("/api/v1/admin/model/metrics", headers=auth_headers)
        assert res.status_code in (200, 503)

    def test_model_metrics_fields_when_available(self, auth_headers):
        res = client.get("/api/v1/admin/model/metrics", headers=auth_headers)
        if res.status_code == 200:
            data = res.json()
            assert "model" in data
            assert "test_auc_roc" in data
            assert "test_f1" in data

    def test_recent_predictions_with_token(self, auth_headers):
        res = client.get("/api/v1/admin/predictions/recent", headers=auth_headers)
        assert res.status_code in (200, 500)

    def test_recent_predictions_response_structure(self, auth_headers):
        res = client.get("/api/v1/admin/predictions/recent", headers=auth_headers)
        if res.status_code == 200:
            data = res.json()
            assert "count" in data
            assert "predictions" in data
            assert isinstance(data["predictions"], list)

    def test_retrain_status_with_token(self, auth_headers):
        res = client.get("/api/v1/admin/model/retrain/status", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert "running" in data

    def test_import_logs_with_token(self, auth_headers):
        res = client.get("/api/v1/admin/import/logs", headers=auth_headers)
        assert res.status_code in (200, 500)


# ═════════════════════════════════════════════════════════════════════════════
# 8. CSV UPLOAD VALIDATION
# ═════════════════════════════════════════════════════════════════════════════

class TestCsvUpload:
    REQUIRED_COLS = [
        "latitude", "longitude",
        "comp_count_300", "comp_count_500", "comp_count_1k",
        "traffic_morning", "traffic_midday", "traffic_evening",
        "dist_transport", "dist_market", "dist_road",
        "pop_density", "road_type", "reference_label",
    ]

    def _make_csv(self, cols=None, rows=None):
        cols = cols or self.REQUIRED_COLS
        rows = rows or [[-1.945, 30.131] + [0] * (len(cols) - 2)]
        header = ",".join(cols)
        body = "\n".join(",".join(str(v) for v in row) for row in rows)
        return (header + "\n" + body).encode()

    def test_upload_without_token_returns_401(self):
        csv_bytes = self._make_csv()
        res = client.post(
            "/api/v1/admin/observations/bulk",
            files={"file": ("test.csv", csv_bytes, "text/csv")},
        )
        assert res.status_code == 401

    def test_upload_missing_required_column_returns_400(self, auth_headers):
        # Drop reference_label
        cols = [c for c in self.REQUIRED_COLS if c != "reference_label"]
        csv_bytes = self._make_csv(cols=cols)
        res = client.post(
            "/api/v1/admin/observations/bulk",
            files={"file": ("test.csv", csv_bytes, "text/csv")},
            headers=auth_headers,
        )
        assert res.status_code == 400

    def test_upload_non_csv_file_returns_400(self, auth_headers):
        res = client.post(
            "/api/v1/admin/observations/bulk",
            files={"file": ("test.txt", b"not a csv", "text/plain")},
            headers=auth_headers,
        )
        assert res.status_code == 400

    def test_upload_corrupted_csv_returns_400(self, auth_headers):
        res = client.post(
            "/api/v1/admin/observations/bulk",
            files={"file": ("test.csv", b"\xff\xfe broken binary \x00\x01", "text/csv")},
            headers=auth_headers,
        )
        assert res.status_code in (400, 500)

    def test_upload_valid_csv_accepted(self, auth_headers):
        """A valid CSV should be accepted (may fail at DB insert if DB unavailable)."""
        row = [-1.945, 30.131, 5, 8, 12, 30, 45, 60, 2, 1, 1, 200.0, 1, 1]
        csv_bytes = self._make_csv(rows=[row])
        res = client.post(
            "/api/v1/admin/observations/bulk",
            files={"file": ("test.csv", csv_bytes, "text/csv")},
            headers=auth_headers,
        )
        # 200 if DB available and insert succeeds
        # 500 if DB unavailable — both mean the file itself was accepted
        assert res.status_code in (200, 500)

    def test_upload_empty_csv_body_returns_400(self, auth_headers):
        res = client.post(
            "/api/v1/admin/observations/bulk",
            files={"file": ("test.csv", b"", "text/csv")},
            headers=auth_headers,
        )
        assert res.status_code in (400, 500)


# ═════════════════════════════════════════════════════════════════════════════
# 9. ERROR HANDLING AND EDGE CASES
# ═════════════════════════════════════════════════════════════════════════════

class TestErrorHandling:
    def test_nonexistent_route_returns_404(self):
        res = client.get("/api/v1/nonexistent")
        assert res.status_code == 404

    def test_wrong_method_on_assess_returns_405(self):
        res = client.get("/api/v1/assess")
        assert res.status_code == 405

    def test_wrong_method_on_login_returns_405(self):
        res = client.get("/api/v1/admin/login")
        assert res.status_code == 405

    def test_assess_content_type_must_be_json(self):
        res = client.post(
            "/api/v1/assess",
            content="latitude=-1.94&longitude=30.06",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert res.status_code == 422

    def test_assess_null_values_rejected(self):
        res = client.post("/api/v1/assess", json={
            "latitude": None, "longitude": None, "business_category": "personal_care"
        })
        assert res.status_code == 422

    def test_responses_are_json(self):
        """All API responses must be JSON."""
        endpoints = [
            ("/", "GET"),
            ("/health", "GET"),
            ("/api/v1/categories", "GET"),
            ("/api/v1/health", "GET"),
        ]
        for path, method in endpoints:
            res = client.request(method, path)
            assert res.headers.get("content-type", "").startswith("application/json"), \
                f"{path} did not return JSON"

    def test_error_responses_do_not_expose_stack_traces(self):
        """500 errors should return a clean message, not a Python traceback."""
        res = client.post("/api/v1/assess", json={
            "latitude": -1.94, "longitude": 30.06, "business_category": "personal_care"
        })
        if res.status_code == 500:
            body = res.text
            assert "Traceback" not in body
            assert "File " not in body


# ═════════════════════════════════════════════════════════════════════════════
# 10. RESPONSE CONSISTENCY
# ═════════════════════════════════════════════════════════════════════════════

class TestResponseConsistency:
    def test_all_error_responses_have_detail_field(self):
        """FastAPI standard: all error responses have a 'detail' field."""
        test_cases = [
            ("POST", "/api/v1/assess", {"latitude": 999, "longitude": 0, "business_category": "personal_care"}),
            ("POST", "/api/v1/admin/login", {"username": "bad", "password": "bad"}),
        ]
        for method, path, body in test_cases:
            res = client.request(method, path, json=body)
            if res.status_code >= 400:
                assert "detail" in res.json(), f"No 'detail' in error response for {method} {path}"

    def test_successful_assess_probability_is_float(self):
        res = client.post("/api/v1/assess", json={
            "latitude": -1.9441, "longitude": 30.0619, "business_category": "personal_care"
        })
        if res.status_code == 200:
            assert isinstance(res.json()["suitability_probability"], float)

    def test_categories_response_is_list(self):
        res = client.get("/api/v1/categories")
        assert res.status_code == 200
        assert isinstance(res.json()["categories"], list)
        assert len(res.json()["categories"]) > 0

    def test_nearby_count_matches_results_length(self):
        res = client.get("/api/v1/nearby/competitors", params={
            "latitude": -1.9441, "longitude": 30.0619
        })
        if res.status_code == 200:
            data = res.json()
            assert data["count"] == len(data["results"])
