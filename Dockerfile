# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: build the React/Vite frontend
# ---------------------------------------------------------------------------
FROM node:20-slim AS frontend-build

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build
# Produces /frontend/dist

# ---------------------------------------------------------------------------
# Stage 2: Python backend, serving the built frontend as static files
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS backend

WORKDIR /app

# System deps for lxml/bs4 etc if needed; kept minimal.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY config/ ./config/

# backend/main.py looks for the built frontend at ../frontend/dist relative
# to backend/, i.e. /app/frontend/dist here.
COPY --from=frontend-build /frontend/dist ./frontend/dist

# Persistent SQLite storage. Railway Volumes get mounted at a path you
# choose (commonly /data) — set DB_PATH to a file inside that mount, e.g.
# DB_PATH=/data/foreclosure.db, via a Railway env var. This local default
# is just for `docker run` without a volume.
ENV DB_PATH=/app/backend/data/foreclosure.db

WORKDIR /app/backend

# Railway (and most PaaS) inject $PORT at runtime; never hardcode a port.
# Using `sh -c` so the shell expands $PORT before uvicorn sees it, with a
# local default of 8000 for `docker run` without -e PORT=...
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
