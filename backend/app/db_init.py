"""Initialises the database: extension, tables, spatial setup, seed data."""

import sys
from sqlalchemy import text
from app.db import engine, Base
import app.models  # noqa: F401 — registers models with Base


def init_db():
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
            conn.commit()
        print("PostGIS extension enabled.")

        Base.metadata.create_all(bind=engine)
        print("Tables created.")

        from app.spatial_setup import create_spatial_functions
        create_spatial_functions()

        from app.seed_data import seed_observations, seed_poi_layer
        seed_observations()
        seed_poi_layer()

        print("\nDatabase initialisation complete.")

    except Exception as exc:
        print(f"Database initialisation failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    init_db()
