"""Seed the database with observations from kigali_spatial_dataset.csv"""

import os
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.models.observation import Observation
from app.db import SessionLocal, engine

# Path to CSV (adjust if running from different location)
CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "backend", "ml", "kigali_spatial_dataset.csv")


def seed_observations():
    """Load observations from CSV and insert into database."""
    
    # Check if CSV exists
    if not os.path.exists(CSV_PATH):
        print(f"⚠ CSV not found at {CSV_PATH}. Skipping seed.")
        return
    
    # Read CSV
    df = pd.read_csv(CSV_PATH)
    print(f"✔ Loaded {len(df)} records from CSV")
    
    db = SessionLocal()
    try:
        # Check if observations already exist
        existing_count = db.execute(text("SELECT COUNT(*) FROM observations")).scalar()
        if existing_count > 0:
            print(f"ℹ Database already contains {existing_count} observations. Skipping seed.")
            return
        
        # For this dataset, we need to provide lat/lon. 
        # The CSV data appears to be from Kigali clusters.
        # We'll use a simple spatial distribution across Kigali (center: -1.9441, 30.0619)
        # Cluster 0, 1, 2 = different geographic zones (synthetic distribution for demo)
        
        cluster_coords = {
            0: (-1.95, 30.06),   # Central
            1: (-1.94, 30.08),   # Northeast
            2: (-1.96, 30.05),   # Southwest
        }
        
        records_added = 0
        for idx, row in df.iterrows():
            cluster_id = int(row['cluster'])
            lat, lon = cluster_coords.get(cluster_id, (-1.9441, 30.0619))
            
            # Add slight variance per index to spread points
            lat += (idx % 10) * 0.003
            lon += (idx % 10) * 0.003
            
            obs = Observation(
                geom=f"SRID=4326;POINT({lon} {lat})",
                biz_category=str(int(row['biz_category']) if pd.notna(row['biz_category']) else 0),
                comp_count_300=int(row['comp_count_300']),
                comp_count_500=int(row['comp_count_500']),
                comp_count_1k=int(row['comp_count_1k']),
                traffic_morning=int(row['traffic_morning']),
                traffic_midday=int(row['traffic_midday']),
                traffic_evening=int(row['traffic_evening']),
                dist_transport=int(row['dist_transport']),
                dist_market=int(row['dist_market']),
                dist_road=int(row['dist_road']),
                pop_density=float(row['pop_density']),
                road_type=bool(int(row['road_type'])),
                stability_label=bool(int(row['stability_label'])),
                cluster_id=cluster_id
            )
            db.add(obs)
            records_added += 1
        
        db.commit()
        print(f"✔ Inserted {records_added} observations")
        
        # Create spatial index for performance
        try:
            db.execute(text("CREATE INDEX IF NOT EXISTS idx_observations_geom ON observations USING GIST(geom)"))
            db.commit()
            print("✔ Created spatial index on observations.geom")
        except Exception as e:
            print(f"⚠ Spatial index creation (may already exist): {e}")
        
    except Exception as e:
        db.rollback()
        print(f"✗ Seed error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_observations()
