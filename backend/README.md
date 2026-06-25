# KigaliSite — Spatial Business Suitability System

A machine learning-based decision-support tool that estimates the spatial suitability of candidate business locations for personal care services (hair salons, barbershops, beauty salons, nail studios) in Kigali, Rwanda.

Built as a BSE Capstone project at African Leadership University, 2026.

---

## What it does

A user opens the map, drops a pin on any candidate location in Kigali, and receives a factor-level spatial assessment — foot traffic patterns, competition density, transport accessibility, market proximity, and residential density — drawn from a field-collected dataset of 187 observed business locations across three commercial clusters.

The system explains which factors drive the result, interprets the location's commercial profile, and gives context-appropriate next steps. It does not predict business success or profitability.

## What it does not do

- It does not predict revenue, profit, or business survival
- It does not assess entrepreneur readiness, capital, or management skills
- It is scoped to personal care services only (proof-of-concept)
- It covers three clusters only: Kimironko, Remera, Kacyiru
- Results outside these mapped areas may be less reliable

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, SQLAlchemy, GeoAlchemy2 |
| Database | PostgreSQL 16, PostGIS 3.4 |
| ML | scikit-learn (Random Forest), SHAP |
| Frontend | React 18, Vite, react-leaflet, Recharts |
| Container | Docker, Docker Compose |
| Web server | Nginx |

---

## Quick start (Docker)

### 1. Copy and fill the environment file

```bash
cp .env.example .env
```

Fill in every value. Do not leave any blank. See [Environment variables](#environment-variables) below.

### 2. Generate a secure SECRET_KEY

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Copy the output into `.env` as `SECRET_KEY=<value>`.

### 3. Generate a bcrypt hash for your admin password

```bash
python -c "import bcrypt; print(bcrypt.hashpw(b'yourpassword', bcrypt.gensalt()).decode())"
```

Copy the output into `.env` as `ADMIN_PASSWORD_HASH=<value>`.

### 4. Start the system

```bash
docker-compose up --build
```

### 5. Verify

| URL | Expected |
|---|---|
| `http://localhost` | React frontend with map |
| `http://localhost:8000/docs` | FastAPI Swagger UI |
| `http://localhost:8000/health` | `{"status": "healthy"}` |
| `http://localhost/admin/login` | Admin login page |

---

## Development (without Docker)

### Backend

```bash
cd backend
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

Create `backend/.env` from `backend/.env.example` and fill in all values.

Initialise the database (requires PostgreSQL + PostGIS running locally):

```bash
python -m app.db_init
```

Start the development server:

```bash
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
```

Create `frontend/.env`:

```env
VITE_API_BASE_URL=http://localhost:8000
```

Start the development server:

```bash
npm run dev
```

Open `http://localhost:5173`.

---

## Environment variables

All variables are required unless marked optional.

| Variable | Description |
|---|---|
| `DATABASE_URL` | Full PostgreSQL connection string |
| `POSTGRES_USER` | Database username |
| `POSTGRES_PASSWORD` | Database password |
| `POSTGRES_DB` | Database name |
| `ADMIN_USERNAME` | Admin panel username |
| `ADMIN_PASSWORD_HASH` | bcrypt hash of admin password (recommended) |
| `ADMIN_PASSWORD` | Plain-text fallback (development only — do not use in production) |
| `SECRET_KEY` | JWT signing key — minimum 32 bytes, generated with `secrets.token_hex(32)` |
| `ALLOWED_ORIGINS` | Comma-separated list of allowed CORS origins |
| `HTTPS_ENABLED` | `true` in production to set Secure cookie flag (default: `false`) |
| `VITE_API_BASE_URL` | Backend URL baked into the frontend at build time |
| `VITE_API_TIMEOUT_MS` | Frontend API timeout in milliseconds (default: 12000) |

**Never commit `.env` to version control.** It is listed in `.gitignore`.

---

## ML model

The Random Forest model is trained via the Jupyter notebook at:

```
backend/ml/KigaliSite_Model_Notebook.ipynb
```

Pre-trained artefacts are stored at:

```
backend/ml/artifacts/
  rf_pipeline.joblib
  shap_explainer.joblib
  model_metadata.json
```

To retrain after adding new observations:

1. Upload new field data via **Admin panel → Import Data**
2. Run **Recompute Spatial Features** to update PostGIS-derived columns
3. Run **Retrain model** — retraining runs as a background task

The model is only saved if AUC-ROC ≥ 0.70 (the minimum threshold for practical decision-support value).

**Model performance (current artefacts):**

| Metric | Value |
|---|---|
| AUC-ROC | 0.9719 |
| F1-Score | 0.6667 |
| OOB Score | 0.8552 |
| Training observations | 145 (Kimironko + Remera) |
| Test observations | 42 (Kacyiru hold-out) |

---

## Data

The reference dataset contains 187 field-collected observations of personal care service locations across three commercial clusters in Gasabo and Kicukiro districts.

| Cluster | Observations |
|---|---|
| Kimironko | 85 |
| Remera | 60 |
| Kacyiru | 42 |

**Class balance:** 132 positive references (stable businesses), 55 negative references. The model uses `class_weight="balanced"` to handle this imbalance.

To seed the database from the CSV:

```bash
python -m app.seed_data
```

---

## API

Full interactive documentation at `http://localhost:8000/docs` (Swagger UI).

Key endpoints:

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/assess` | Spatial suitability assessment |
| `GET` | `/api/v1/categories` | Supported business categories |
| `GET` | `/api/v1/nearby/competitors` | Nearby reference observations |
| `GET` | `/api/v1/health` | Liveness check |
| `POST` | `/api/v1/admin/login` | Admin authentication |
| `POST` | `/api/v1/admin/observations/bulk` | Bulk CSV import |
| `POST` | `/api/v1/admin/observations/recompute-spatial` | Recompute PostGIS features |
| `POST` | `/api/v1/admin/model/retrain` | Trigger background retraining |
| `GET` | `/api/v1/admin/model/retrain/status` | Poll retraining progress |
| `GET` | `/api/v1/admin/model/metrics` | Current model metadata |

---

## Tests

```bash
cd backend
pip install pytest httpx
pytest tests/test_api.py -v
```

The test suite covers authentication, authorization, input validation, error handling, admin endpoints, CSV upload validation, and response consistency across all public and protected routes.

---

## Known limitations

| Limitation | Notes |
|---|---|
| Single business category | Personal care services only. Extensible to other categories with additional field data. |
| Three cluster coverage | Model trained on Kimironko, Remera, Kacyiru only. Reliability outside these areas is reduced. |
| Dataset scale | 187 observations — proof-of-concept scale, not production-scale ML. |
| No HTTPS in development | Required for public deployment. Set `HTTPS_ENABLED=true` and configure a reverse proxy. |
| CORS | Configured via `ALLOWED_ORIGINS` environment variable. Must be set correctly for production. |
| Rate limiting | `/api/v1/assess` is limited to 30 requests/minute per IP. No rate limiting on other public endpoints. |
| No mobile pin input | Location selection requires a map click. No manual coordinate entry for accessibility. |

---

## Project links

- Frontend repository: https://github.com/Alliance-D/Business-Spatial-suitability-recommendation-frontend.git
- Demo video: https://youtu.be/Ql3eeYIyQyw
- Research report: https://docs.google.com/document/d/1zhPXuk-C4jSV5Wq2OILvuvV3lHRG8ozHfMWlV3TQZys/edit?usp=sharing
