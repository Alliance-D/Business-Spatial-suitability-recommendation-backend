"""
Simple migration runner for local/dev use.

Usage:
  Set `DATABASE_URL` environment variable (e.g. postgresql://user:pass@host:5432/dbname)
  Then run: python scripts/run_migrations.py

This script will apply all .sql files in the ../migrations directory in lexical order.
"""
import os
import glob
import psycopg2


def get_db_conn():
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise SystemExit('DATABASE_URL not set')
    return psycopg2.connect(url)


def apply_sql_file(cur, path):
    print('Applying', path)
    with open(path, 'r', encoding='utf-8') as fh:
        sql = fh.read()
    cur.execute(sql)


def main():
    migrations_dir = os.path.join(os.path.dirname(__file__), '..', 'migrations')
    files = sorted(glob.glob(os.path.join(migrations_dir, '*.sql')))
    if not files:
        print('No migrations found in', migrations_dir)
        return

    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                for f in files:
                    apply_sql_file(cur, f)
        print('Migrations applied successfully')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
