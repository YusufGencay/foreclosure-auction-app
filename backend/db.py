"""
db.py - SQLAlchemy engine/session setup for the foreclosure analysis tool.
SQLite database is intended to live at backend/data/foreclosure.db. Some
mounted/synced filesystems (e.g. certain cloud-synced "outputs" mounts)
don't support proper POSIX file locking, which breaks SQLite's journal
mode. We do a quick write self-test at import time and fall back to a
local (non-mounted) path if the primary location isn't usable, so the app
still works reliably in those environments.
"""
import sqlite3
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from config import DB_PATH, DATA_DIR

FALLBACK_DB_PATH = "/tmp/foreclosure-app-data/foreclosure.db"


def _write_self_test(path) -> bool:
    try:
        conn = sqlite3.connect(str(path))
        conn.execute("CREATE TABLE IF NOT EXISTS _write_test (x INTEGER)")
        conn.execute("INSERT INTO _write_test (x) VALUES (1)")
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


if _write_self_test(DB_PATH):
    ACTIVE_DB_PATH = DB_PATH
else:
    import os
    os.makedirs("/tmp/foreclosure-app-data", exist_ok=True)
    print(
        f"[db] WARNING: configured sqlite path '{DB_PATH}' failed a write "
        f"self-test (likely a mount without POSIX file locking). Falling "
        f"back to '{FALLBACK_DB_PATH}'."
    )
    ACTIVE_DB_PATH = FALLBACK_DB_PATH

DATABASE_URL = f"sqlite:///{ACTIVE_DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# SQLAlchemy type -> SQLite column type affinity, used only by
# ensure_columns() below.
_SQLITE_TYPE_MAP = {
    "INTEGER": "INTEGER",
    "FLOAT": "FLOAT",
    "BOOLEAN": "BOOLEAN",
    "DATETIME": "DATETIME",
    "VARCHAR": "VARCHAR",
    "TEXT": "TEXT",
    "JSON": "JSON",
}


def ensure_columns(engine, base):
    """
    Lightweight, dependency-free auto-migration for SQLite: this project
    has no Alembic/migration framework, and Base.metadata.create_all()
    only creates tables that don't exist yet - it silently does nothing if
    a table already exists but is missing columns a newer models.py added
    (e.g. the Phase 1 zillow_estimate/realtor_estimate/redfin_estimate/
    market_conditions/ranking_score/estimates_last_updated columns added to
    Property). Without this, an existing data/foreclosure.db from before
    those columns were added would throw "no such column" errors at
    runtime instead of just picking up the new columns.

    For every table/column defined in the ORM models, this adds any
    missing column via a plain `ALTER TABLE ... ADD COLUMN` (SQLite
    supports adding nullable columns this way). Never drops or alters
    existing columns/data - purely additive and safe to run on every
    startup.
    """
    with engine.connect() as conn:
        for table_name, table in base.metadata.tables.items():
            existing_cols = {
                row[1]  # PRAGMA table_info: cid, name, type, notnull, dflt_value, pk
                for row in conn.exec_driver_sql(f"PRAGMA table_info('{table_name}')").fetchall()
            }
            if not existing_cols:
                continue  # table doesn't exist yet - create_all() will handle it
            for column in table.columns:
                if column.name in existing_cols:
                    continue
                col_type = _SQLITE_TYPE_MAP.get(
                    column.type.__class__.__name__.upper(), "TEXT"
                )
                conn.exec_driver_sql(
                    f"ALTER TABLE '{table_name}' ADD COLUMN '{column.name}' {col_type}"
                )
                print(f"[db] Added missing column '{column.name}' ({col_type}) to table '{table_name}'.")
        conn.commit()
