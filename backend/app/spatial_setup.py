"""Database setup utilities and SQL functions for spatial queries."""

from sqlalchemy import text
from app.db import engine

def create_spatial_functions():
    """Create PostGIS spatial functions and views for efficient querying."""
    
    sql_setup = """
    -- Spatial index on observations geometry
    CREATE INDEX IF NOT EXISTS idx_observations_geom ON observations USING GIST(geom);
    
    -- Function: Get competing businesses within radius (meters)
    CREATE OR REPLACE FUNCTION get_competitors_by_radius(
        p_lon FLOAT, 
        p_lat FLOAT, 
        p_radius_m INT
    )
    RETURNS TABLE (competitor_count INT) AS $$
    BEGIN
        RETURN QUERY
        SELECT COUNT(*)::INT AS competitor_count
        FROM observations
        WHERE ST_DWithin(
            geom::geography,
            ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326)::geography,
            p_radius_m
        );
    END;
    $$ LANGUAGE plpgsql IMMUTABLE;
    
    -- Function: Get average traffic within radius
    CREATE OR REPLACE FUNCTION get_avg_traffic(
        p_lon FLOAT,
        p_lat FLOAT,
        p_radius_m INT
    )
    RETURNS TABLE (morning FLOAT, midday FLOAT, evening FLOAT) AS $$
    BEGIN
        RETURN QUERY
        SELECT 
            COALESCE(AVG(traffic_morning), 0)::FLOAT,
            COALESCE(AVG(traffic_midday), 0)::FLOAT,
            COALESCE(AVG(traffic_evening), 0)::FLOAT
        FROM observations
        WHERE ST_DWithin(
            geom::geography,
            ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326)::geography,
            p_radius_m
        );
    END;
    $$ LANGUAGE plpgsql IMMUTABLE;
    
    -- Function: Get nearest observation distance
    CREATE OR REPLACE FUNCTION get_nearest_distance(
        p_lon FLOAT,
        p_lat FLOAT
    )
    RETURNS TABLE (distance_m FLOAT) AS $$
    BEGIN
        RETURN QUERY
        SELECT 
            COALESCE(
                MIN(ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326)::geography))::FLOAT,
                0
            )
        FROM observations;
    END;
    $$ LANGUAGE plpgsql IMMUTABLE;
    
    -- View: Observation clusters (for heatmap/aggregation)
    CREATE OR REPLACE VIEW observation_clusters AS
    SELECT 
        cluster_id,
        COUNT(*) as obs_count,
        AVG(ST_X(geom::geometry)) as center_lon,
        AVG(ST_Y(geom::geometry)) as center_lat,
        AVG(traffic_morning + traffic_midday + traffic_evening) as avg_total_traffic,
        AVG(pop_density) as avg_pop_density,
        SUM(CASE WHEN stability_label = true THEN 1 ELSE 0 END)::FLOAT / 
            COUNT(*) as stability_ratio
    FROM observations
    GROUP BY cluster_id;
    
    -- Summary statistics
    CREATE OR REPLACE VIEW observation_summary AS
    SELECT 
        COUNT(*) as total_observations,
        COUNT(DISTINCT cluster_id) as num_clusters,
        AVG(pop_density) as avg_population_density,
        SUM(CASE WHEN stability_label = true THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as stable_ratio,
        MIN(created_at) as earliest_record,
        MAX(created_at) as latest_record
    FROM observations;
    
    
    try:
        with engine.connect() as conn:
            for statement in sql_setup.split(';'):
                if statement.strip():
                    conn.execute(text(statement))
            conn.commit()
            print("\u2714 Spatial functions and views created")
    except Exception as e:
        print(f"\u26a0 Spatial setup (may already exist): {e}")
        """

def check_postgis():
    """Verify PostGIS is installed and operational."""
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT PostGIS_Version()")).scalar()
            print(f"\u2714 PostGIS ready: {version}")
            return True
    except Exception as e:
        print(f"\u2717 PostGIS check failed: {e}")
        return False

if __name__ == "__main__":
    check_postgis()
    create_spatial_functions()
