# Spatial Suitability Backend

FastAPI backend for a spatial suitability recommendation system for salon location assessment in Kigali, Rwanda.

The backend provides API endpoints for spatial suitability queries, nearby observation lookup, population density layers, admin tools, and database initialization using PostgreSQL/PostGIS.

## Tech Stack

* Python
* FastAPI
* PostgreSQL
* PostGIS
* SQLAlchemy
* Uvicorn
* Pandas

## Project Structure

```text
backend/
  app/
    models/
    routers/
    schemas/
    services/
    db.py
    db_init.py
    main.py
    seed_data.py
    spatial_setup.py
  migrations/
  ml/
  scripts/
  requirements.txt
  Dockerfile
  .env.example
```

## Requirements

Install the following before setup:

* Python 3.10+
* PostgreSQL
* PostGIS extension
* Git

## Environment Setup

Create and activate a virtual environment:

```powershell
python -m venv venv
.\venv\Scripts\activate
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Create a `.env` file in the backend root:

```env
DATABASE_URL=postgresql://suitability_user:your_password@localhost:5432/suitability_db
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_admin_password
SECRET_KEY=your_secret_key
```

Do not commit `.env` to GitHub.

## Database Setup

Create a PostgreSQL database first. Then initialize tables, PostGIS, spatial functions, and seed data:

```powershell
python -m app.db_init
```

To check whether observations were inserted:

```powershell
python -c "from app.db import SessionLocal; from sqlalchemy import text; db=SessionLocal(); print(db.execute(text('SELECT COUNT(*) FROM observations')).fetchall()); db.close()"
```

## Running Locally

Start the FastAPI server:

```powershell
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open API documentation:

```text
http://localhost:8000/docs
```

Health check:

```text
http://localhost:8000/health
```

## Main API Endpoint

### POST `/api/v1/query`

Example request:

```json
{
  "latitude": -1.9366,
  "longitude": 30.1304,
  "business_category": "salon",
  "radius_meters": 1000
}
```

Example response includes:

* suitability score
* suitability label
* factor breakdown
* positive and negative factors
* disclaimer

## Deployment on Render

Create a PostgreSQL database on Render first, then create a backend Web Service.

Render settings:

```text
Build Command:
pip install -r requirements.txt

Start Command:
python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Environment variables:

```env
DATABASE_URL=your_render_postgresql_url
ADMIN_USERNAME=your_admin_username
ADMIN_PASSWORD=your_admin_password
SECRET_KEY=your_secret_key
```

After deployment, initialize the Render database from your local backend folder:

```powershell
$env:DATABASE_URL="your_render_postgresql_url"
python -m app.db_init
```

Then confirm:

```powershell
$env:DATABASE_URL="your_render_postgresql_url"
python -c "from app.db import SessionLocal; from sqlalchemy import text; db=SessionLocal(); print(db.execute(text('SELECT COUNT(*) FROM observations')).fetchall()); db.close()"
```

## Notes

This is a prototype decision-support system. It provides spatial suitability guidance based on available observation data. It does not predict business success or failure.



# Link to frontend repo:
https://github.com/Alliance-D/Business-Spatial-suitability-recommendation-frontend.git

# Link to Youtube:


# Link to report:
https://docs.google.com/document/d/1zhPXuk-C4jSV5Wq2OILvuvV3lHRG8ozHfMWlV3TQZys/edit?usp=sharing