"""
Database setup: column migrations, spatial indexes, and helper SQL views.

Handles the case where tables were created before certain columns were added
to the SQLAlchemy models. SQLAlchemy's create_all() does not ALTER existing
tables, so we do it here explicitly using IF NOT EXISTS guards.
Safe to run on every startup — all statements are idempotent.
"""

from sqlalchemy import text
from app.db import engine

# ── Column migrations ─────────────────────────────────────────────────────────
COLUMN_MIGRATIONS = [
    # observations table
    """
    DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='observations' AND column_name='reference_label'
        ) THEN
            ALTER TABLE observations ADD COLUMN reference_label BOOLEAN NOT NULL DEFAULT FALSE;
            CREATE INDEX IF NOT EXISTS idx_observations_reference_label ON observations(reference_label);
        END IF;
    END $$;
    """,
    """
    DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='observations' AND column_name='cluster_id'
        ) THEN
            ALTER TABLE observations ADD COLUMN cluster_id INTEGER;
            CREATE INDEX IF NOT EXISTS idx_observations_cluster_id ON observations(cluster_id);
        END IF;
    END $$;
    """,
    """
    DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='observations' AND column_name='cluster_name'
        ) THEN
            ALTER TABLE observations ADD COLUMN cluster_name VARCHAR;
            CREATE INDEX IF NOT EXISTS idx_observations_cluster_name ON observations(cluster_name);
        END IF;
    END $$;
    """,
    """
    DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='observations' AND column_name='updated_at'
        ) THEN
            ALTER TABLE observations ADD COLUMN updated_at TIMESTAMP DEFAULT NOW();
        END IF;
    END $$;
    """,
    """
    DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='observations' AND column_name='comp_count_300'
        ) THEN
            ALTER TABLE observations ADD COLUMN comp_count_300 INTEGER;
        END IF;
    END $$;
    """,
    """
    DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='observations' AND column_name='comp_count_500'
        ) THEN
            ALTER TABLE observations ADD COLUMN comp_count_500 INTEGER;
        END IF;
    END $$;
    """,
    """
    DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='observations' AND column_name='comp_count_1k'
        ) THEN
            ALTER TABLE observations ADD COLUMN comp_count_1k INTEGER;
        END IF;
    END $$;
    """,
    """
    DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='observations' AND column_name='pop_density'
        ) THEN
            ALTER TABLE observations ADD COLUMN pop_density FLOAT;
        END IF;
    END $$;
    """,

    # prediction_log table — add columns that exist in the model but not the table
    """
    DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='prediction_log' AND column_name='ip_address'
        ) THEN
            ALTER TABLE prediction_log ADD COLUMN ip_address VARCHAR;
        END IF;
    END $$;
    """,
    """
    DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='prediction_log' AND column_name='business_category'
        ) THEN
            ALTER TABLE prediction_log ADD COLUMN business_category VARCHAR;
        END IF;
    END $$;
    """,
    """
    DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='prediction_log' AND column_name='predicted_label'
        ) THEN
            ALTER TABLE prediction_log ADD COLUMN predicted_label BOOLEAN;
        END IF;
    END $$;
    """,
]

# ── Spatial indexes ───────────────────────────────────────────────────────────
INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS idx_observations_geom     ON observations  USING GIST(geom);",
    "CREATE INDEX IF NOT EXISTS idx_poi_market_geom       ON poi_market    USING GIST(geom);",
    "CREATE INDEX IF NOT EXISTS idx_poi_transport_geom    ON poi_transport USING GIST(geom);",
    "CREATE INDEX IF NOT EXISTS idx_poi_road_geom         ON poi_road      USING GIST(geom);",
]

# ── Views ─────────────────────────────────────────────────────────────────────
VIEW_STATEMENTS = [
    """
    CREATE OR REPLACE VIEW observation_cluster_summary AS
    SELECT
        COALESCE(cluster_name, 'Cluster ' || cluster_id::text, 'Unknown') AS cluster_label,
        cluster_id,
        COUNT(*) AS obs_count,
        SUM(CASE WHEN stability_label THEN 1 ELSE 0 END)      AS positive_references,
        SUM(CASE WHEN NOT stability_label THEN 1 ELSE 0 END)  AS negative_references,
        AVG(pop_density)                                        AS avg_pop_density,
        AVG(traffic_morning + traffic_midday + traffic_evening) AS avg_total_traffic
    FROM observations
    GROUP BY cluster_name, cluster_id;
    """,
    """
    CREATE OR REPLACE VIEW observation_summary AS
    SELECT
        COUNT(*)                                                     AS total_observations,
        COUNT(DISTINCT COALESCE(cluster_id::text, cluster_name))    AS num_clusters,
        SUM(CASE WHEN stability_label THEN 1 ELSE 0 END)            AS positive_references,
        SUM(CASE WHEN NOT stability_label THEN 1 ELSE 0 END)        AS negative_references,
        AVG(pop_density)                                             AS avg_population_density,
        MIN(created_at)                                              AS earliest_record,
        MAX(created_at)                                              AS latest_record
    FROM observations;
    """,
]


def create_spatial_functions():
    """
    Run column migrations, create spatial indexes, and create/replace views.
    Safe to call on every startup — all statements are idempotent.
    """
    with engine.connect() as conn:
        for stmt in COLUMN_MIGRATIONS:
            conn.execute(text(stmt))
        conn.commit()

        for stmt in INDEX_STATEMENTS:
            conn.execute(text(stmt))
        conn.commit()

        for stmt in VIEW_STATEMENTS:
            conn.execute(text(stmt))
        conn.commit()

    print("Spatial indexes, column migrations, and views applied.")


def check_postgis():
    with engine.connect() as conn:
        version = conn.execute(text("SELECT PostGIS_Version()")).scalar()
        print(f"PostGIS ready: {version}")
        return version


if __name__ == "__main__":
    check_postgis()
    create_spatial_functions()
