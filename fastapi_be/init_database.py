#!/usr/bin/env python3
"""
Initialize PostgreSQL database for HOIM System.

Usage:
    cd /home/xusheng/workspace/hoimsystem/fastapi_be
    PYTHONPATH=$(pwd) python3 init_database.py

This script will:
  1. Connect to the default 'postgres' database
  2. Create the target database if it does not exist
  3. Create all tables from SQLAlchemy models

Environment variables (optional, defaults match app/config.py):
  DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME
"""

import os
import sys
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import settings

DB_ADMIN = "postgres"


def create_database():
    """Create the target PostgreSQL database if it does not exist."""
    conn = None
    try:
        conn = psycopg2.connect(
            dbname=DB_ADMIN,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            host=settings.DB_HOST,
            port=settings.DB_PORT,
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()

        cur.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (settings.DB_NAME,),
        )
        exists = cur.fetchone()

        if exists:
            print(f"[INFO] Database '{settings.DB_NAME}' already exists.")
        else:
            cur.execute(f'CREATE DATABASE "{settings.DB_NAME}"')
            print(f"[OK] Database '{settings.DB_NAME}' created successfully.")

        cur.close()
    except psycopg2.Error as e:
        print(f"[ERROR] Failed to create database: {e}")
        sys.exit(1)
    finally:
        if conn:
            conn.close()


def create_tables():
    """Create all tables from SQLAlchemy models."""
    try:
        from app.database import engine, Base
        import app.models

        Base.metadata.create_all(bind=engine)
        print("[OK] All tables created successfully.")
    except Exception as e:
        print(f"[ERROR] Failed to create tables: {e}")
        sys.exit(1)


def main():
    print(f"[INFO] Database target: postgresql://{settings.DB_USER}:*****@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")
    create_database()
    create_tables()
    print("[DONE] Database initialization complete.")


if __name__ == "__main__":
    main()
