"""
config.py - loads environment variables and config/counties.yaml for the
Florida Foreclosure Auction Analysis & Ranking Tool backend.
"""
import os
from pathlib import Path
import yaml
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
APP_ROOT = BACKEND_DIR.parent
ENV_PATH = APP_ROOT / ".env"

# Load .env if present (falls back silently to real env vars / defaults otherwise)
load_dotenv(dotenv_path=ENV_PATH if ENV_PATH.exists() else None)

# --- Server-side only secrets/config. Never expose these to the frontend. ---
TITLE_SEARCH_API_KEY = os.getenv("TITLE_SEARCH_API_KEY", "").strip()
TITLE_SEARCH_PROVIDER = os.getenv("TITLE_SEARCH_PROVIDER", "").strip()
CRIME_DATA_API_KEY = os.getenv("CRIME_DATA_API_KEY", "").strip()
FEMA_API_BASE_URL = os.getenv("FEMA_API_BASE_URL", "https://www.fema.gov/api/open/v2").strip()

COUNTIES_YAML_PATH = APP_ROOT / "config" / "counties.yaml"

DATA_DIR = BACKEND_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# DB_PATH is configurable via env var so it can point at a persistent
# volume in production (e.g. Railway Volumes are mounted at /data).
# Falls back to the local backend/data/foreclosure.db used in dev.
_db_path_env = os.getenv("DB_PATH", "").strip()
if _db_path_env:
    DB_PATH = Path(_db_path_env)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
else:
    DB_PATH = DATA_DIR / "foreclosure.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"


def load_counties_config():
    """Load config/counties.yaml into a list of dicts. Returns [] if missing."""
    if not COUNTIES_YAML_PATH.exists():
        return []
    with open(COUNTIES_YAML_PATH, "r") as f:
        data = yaml.safe_load(f) or {}
    return data.get("counties", [])
