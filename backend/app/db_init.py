"""Initialize database and create tables."""

import sys
from sqlalchemy import text
from app.db import engine, Base
import app.models  # Import to register models

def init_db():
    """Create all tables, enable PostGIS extension, and seed data."""
    try:
        # Enable PostGIS extension
        with engine.connect() as conn:
            try:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
                print("✔ PostGIS extension enabled")
            except Exception as e:
                print(f"⚠ PostGIS enable (may already exist): {e}")
            conn.commit()
        
        # Create all tables
        Base.metadata.create_all(bind=engine)
        print("✔ Database tables created")
                # Create spatial functions and views
        try:
            from app.spatial_setup import create_spatial_functions
            create_spatial_functions()
        except Exception as e:
            print(f"ℹ Spatial setup error: {e}")
                # Seed data from CSV
        try:
            from app.seed_data import seed_observations
            seed_observations()
        except ImportError:
            print(f"⚠ Seed import failed: {e}")
        except Exception as e:
            print(f"⚠ Seeding error: {e}")
        
        print("\n✔ Database initialization complete!")
        print("\nTables created:")
        print("  - observations (with spatial index)")
        print("  - model_artefact")
        print("  - prediction_log")
        
    except Exception as e:
        print(f"✗ Database initialization failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    init_db()
