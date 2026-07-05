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
