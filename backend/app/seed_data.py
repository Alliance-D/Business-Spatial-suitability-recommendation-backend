"""Seeds the database with the reference dataset and POI layer."""

import json
import os
import pandas as pd
from sqlalchemy import text

from app.db import SessionLocal
from app.models.observation import Observation, POIMarket, POITransport, POIRoad

BASE_DIR = os.path.dirname(__file__)
ML_DIR   = os.path.join(BASE_DIR, "..", "ml")
CSV_PATH = os.path.join(ML_DIR, "kigali_personal_care_dataset.csv")
POI_PATH = os.path.join(ML_DIR, "poi_layer.json")


def seed_observations():
    if not os.path.exists(CSV_PATH):
        print(f"Dataset not found at {CSV_PATH}. Skipping observation seed.")
        return

    db = SessionLocal()
    try:
        existing = db.execute(text("SELECT COUNT(*) FROM observations")).scalar()
        if existing > 0:
            print(f"observations already has {existing} rows. Skipping seed.")
            return

        df = pd.read_csv(CSV_PATH)
        inserted = 0

        for _, row in df.iterrows():
            label = bool(int(row["reference_label"]))
            db.add(Observation(
                geom=f"SRID=4326;POINT({row['longitude']} {row['latitude']})",
                # stability_label is the original NOT NULL column — set it to the label value
                stability_label=label,
                # reference_label is the column added later — keep in sync
                reference_label=label,
                comp_count_300=int(row["comp_count_300"]),
                comp_count_500=int(row["comp_count_500"]),
                comp_count_1k=int(row["comp_count_1k"]),
                traffic_morning=int(row["traffic_morning"]),
                traffic_midday=int(row["traffic_midday"]),
                traffic_evening=int(row["traffic_evening"]),
                dist_transport=int(row["dist_transport"]),
                dist_market=int(row["dist_market"]),
                dist_road=int(row["dist_road"]),
                pop_density=float(row["pop_density"]),
                road_type=bool(int(row["road_type"])),
                cluster_id=int(row["cluster"]),
                cluster_name=str(row["cluster_name"]),
            ))
            inserted += 1

        db.commit()
        print(f"Inserted {inserted} observations.")

    except Exception as exc:
        db.rollback()
        print(f"Observation seed failed: {exc}")
        raise
    finally:
        db.close()


def seed_poi_layer():
    if not os.path.exists(POI_PATH):
        print(f"POI layer not found at {POI_PATH}. Skipping POI seed.")
        return

    db = SessionLocal()
    try:
        existing = db.execute(text("SELECT COUNT(*) FROM poi_market")).scalar()
        if existing > 0:
            print(f"poi_market already has {existing} rows. Skipping POI seed.")
            return

        with open(POI_PATH) as f:
            poi = json.load(f)

        for m in poi["markets"]:
            db.add(POIMarket(name=m["name"], geom=f"SRID=4326;POINT({m['lon']} {m['lat']})"))

        for t in poi["transport"]:
            db.add(POITransport(name=t["name"], geom=f"SRID=4326;POINT({t['lon']} {t['lat']})"))

        for r in poi["roads"]:
            wkt_points = ", ".join(f"{p[1]} {p[0]}" for p in r["points"])
            db.add(POIRoad(name=r["name"], geom=f"SRID=4326;LINESTRING({wkt_points})"))

        db.commit()
        print(f"Inserted {len(poi['markets'])} markets, {len(poi['transport'])} "
              f"transport stops, {len(poi['roads'])} roads.")

    except Exception as exc:
        db.rollback()
        print(f"POI seed failed: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_observations()
    seed_poi_layer()
