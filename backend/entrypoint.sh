#!/bin/sh
set -e

# Wait for the database to accept connections
echo "Waiting for database..."
until python -c "
import sys, time
from sqlalchemy import create_engine, text
import os
url = os.environ.get('DATABASE_URL', 'postgresql://suitability_user:postgre_password@db:5432/suitability_db')
try:
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(text('SELECT 1'))
except Exception as e:
    sys.exit(1)
"; do
  sleep 1
done
echo "Database is up."

# Idempotent: creates extension/tables/views, seeds reference data and POI
# layer only if not already present.
python -m app.db_init

exec uvicorn main:app --host 0.0.0.0 --port 8000
