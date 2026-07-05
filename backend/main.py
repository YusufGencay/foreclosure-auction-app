"""
main.py - FastAPI application for the Florida Foreclosure Auction Analysis
& Ranking Tool.

This is a decision-support tool for real-estate investors, NOT a
scraping-guarantee tool. See scrapers/realforeclose.py and
scrapers/grantstreet.py for honest documentation of what actually works vs.
what requires manual verification or a headless browser.
"""
import io
import logging
from datetime import datetime, date
from typing import List, Optional

import pandas as pd
from pathlib import Path as _Path

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler

from db import Base, engine, get_db, SessionLocal
from models import County, Property, ScrapeLog, ScoreWeight
from config import load_counties_config, TITLE_SEARCH_API_KEY, TITLE_SEARCH_PROVIDER
from scrapers.sample_data import seed_sample_data
from scrapers.base import run_scraper_safely, ScrapeResult
from scrapers.realauction_playwright import RealAuctionPlaywrightScraper
from scrapers.grantstreet import GrantStreetScraper
from scoring import compute_score

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

app = FastAPI(title="FL Foreclosure Auction Analysis & Ranking Tool")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DEFAULT_WEIGHTS = {
    "equity_spread": 1.0,
    "absorption_rate": 0.0,  # placeholder component, no data source
    "crime_rate": 0.3,
    "lien_priority": 1.0,
    "taxes_owed": 0.5,
    "code_liens": 0.4,
    "flood_zone": 0.3,
    "bankruptcy": 0.8,
    "hoa_balance": 0.5,
}

WEIGHT_DESCRIPTIONS = {
    "equity_spread": "market_value - final_judgment; strong positive if >= $200k",
    "absorption_rate": "PLACEHOLDER - no free data source integrated yet",
    "crime_rate": "FBI Crime Data API by zip; unavailable if no API key configured",
    "lien_priority": "Large penalty if HOA-COA plaintiff or senior lien survives sale",
    "taxes_owed": "Proportional penalty for outstanding property taxes",
    "code_liens": "Proportional penalty for outstanding code enforcement liens",
    "flood_zone": "FEMA flood zone risk adjustment (placeholder if unknown)",
    "bankruptcy": "Penalty + warning if bankruptcy_flag is set",
    "hoa_balance": "Proportional penalty for outstanding HOA/COA balance",
}

SCRAPER_REGISTRY = {
    # Both realforeclose.com and realtaxdeed.com are the same underlying
    # RealAuction/Realauction.com LLC white-label platform (confirmed
    # identical div.AUCTION_ITEM/table.ad_tab structure on both during
    # live inspection 2026-07-04) - one Playwright adapter covers both.
    "realforeclose": RealAuctionPlaywrightScraper,
    "realtaxdeed": RealAuctionPlaywrightScraper,
    "grantstreet_clerkauction": GrantStreetScraper,
}

scheduler = BackgroundScheduler()


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _seed_weights(db)
        _load_counties(db)
        inserted = seed_sample_data(db)
        if inserted:
            logger.info("Seeded %d demo properties (SAMPLE_DEMO_DATA_NOT_REAL).", inserted)
        _rescore_all(db)
    finally:
        db.close()

    if not scheduler.running:
        scheduler.add_job(
            _scrape_all_job,
            "cron",
            hour=3,
            minute=0,
            id="daily_scrape_all",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("Scheduler started: daily scrape-all job registered for 03:00.")


@app.on_event("shutdown")
def on_shutdown():
    if scheduler.running:
        scheduler.shutdown(wait=False)


def _seed_weights(db: Session):
    if db.query(ScoreWeight).count() > 0:
        return
    for key, weight in DEFAULT_WEIGHTS.items():
        db.add(ScoreWeight(key=key, weight=weight, description=WEIGHT_DESCRIPTIONS.get(key, "")))
    db.commit()


def _load_counties(db: Session):
    counties = load_counties_config()
    for c in counties:
        existing = db.query(County).filter(County.name == c.get("county")).first()
        if existing:
            existing.region = c.get("region")
            existing.platform = c.get("platform")
            existing.portal_url = c.get("portal_url")
            existing.verified = c.get("verified", False)
            existing.notes = c.get("notes")
        else:
            db.add(County(
                name=c.get("county"),
                region=c.get("region"),
                platform=c.get("platform"),
                portal_url=c.get("portal_url"),
                verified=c.get("verified", False),
                notes=c.get("notes"),
            ))
    db.commit()


def _get_weights_dict(db: Session) -> dict:
    rows = db.query(ScoreWeight).all()
    if not rows:
        return dict(DEFAULT_WEIGHTS)
    return {r.key: r.weight for r in rows}


def _rescore_all(db: Session):
    weights = _get_weights_dict(db)
    for prop in db.query(Property).all():
        result = compute_score(prop, weights)
        prop.composite_score = result["composite_score"]
        # equity_spread raw dollar value always recomputed/shown
        prop.equity_spread = (prop.market_value or 0.0) - (prop.final_judgment or 0.0)
    db.commit()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class PropertyUpdate(BaseModel):
    notes: Optional[str] = None
    flag_status: Optional[str] = None
    rehab_estimate_user_input: Optional[float] = None


class WeightUpdateItem(BaseModel):
    key: str
    weight: float


class WeightsUpdate(BaseModel):
    weights: List[WeightUpdateItem]


def _property_to_dict(prop: Property, db: Session) -> dict:
    weights = _get_weights_dict(db)
    score = compute_score(prop, weights)
    return {
        "id": prop.id,
        "case_number": prop.case_number,
        "county": prop.county,
        "sale_date": prop.sale_date,
        "owner_name": prop.owner_name,
        "address": prop.address,
        "parcel_id": prop.parcel_id,
        "legal_description": prop.legal_description,
        "property_type": prop.property_type,
        "beds": prop.beds,
        "baths": prop.baths,
        "sqft": prop.sqft,
        "year_built": prop.year_built,
        "final_judgment": prop.final_judgment,
        "opening_bid": prop.opening_bid,
        "assessed_value": prop.assessed_value,
        "market_value": prop.market_value,
        "plaintiff_name": prop.plaintiff_name,
        "plaintiff_type": prop.plaintiff_type,
        "occupancy_status": prop.occupancy_status,
        "lien_priority_status": prop.lien_priority_status,
        "senior_lien_survives": prop.senior_lien_survives,
        "taxes_owed": prop.taxes_owed,
        "code_liens": prop.code_liens,
        "flood_zone": prop.flood_zone,
        "insurance_estimate": prop.insurance_estimate,
        "comps_json": prop.comps_json,
        "bankruptcy_flag": prop.bankruptcy_flag,
        "redemption_notes": prop.redemption_notes,
        "hoa_balance": prop.hoa_balance,
        "rehab_estimate_user_input": prop.rehab_estimate_user_input,
        "notes": prop.notes,
        "flag_status": prop.flag_status,
        "source_url": prop.source_url,
        "is_demo_data": prop.is_demo_data,
        "last_scraped_at": prop.last_scraped_at,
        "equity_spread": (prop.market_value or 0.0) - (prop.final_judgment or 0.0),
        "composite_score": score["composite_score"],
        "component_breakdown": score["component_breakdown"],
        "warnings": score["warnings"],
    }


# ---------------------------------------------------------------------------
# Properties endpoints
# ---------------------------------------------------------------------------
@app.get("/api/properties")
def list_properties(
    county: Optional[str] = None,
    sale_date_from: Optional[date] = None,
    sale_date_to: Optional[date] = None,
    min_equity_spread: Optional[float] = None,
    plaintiff_type: Optional[str] = None,
    occupancy_status: Optional[str] = None,
    flag_status: Optional[str] = None,
    sort_by: str = Query("composite_score", description="Field to sort by"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(Property)
    if county:
        query = query.filter(Property.county == county)
    if sale_date_from:
        query = query.filter(Property.sale_date >= sale_date_from)
    if sale_date_to:
        query = query.filter(Property.sale_date <= sale_date_to)
    if plaintiff_type:
        query = query.filter(Property.plaintiff_type == plaintiff_type)
    if occupancy_status:
        query = query.filter(Property.occupancy_status == occupancy_status)
    if flag_status:
        query = query.filter(Property.flag_status == flag_status)

    rows = query.all()

    if min_equity_spread is not None:
        rows = [r for r in rows if ((r.market_value or 0.0) - (r.final_judgment or 0.0)) >= min_equity_spread]

    results = [_property_to_dict(r, db) for r in rows]

    sortable_fields = {"composite_score", "equity_spread", "sale_date", "final_judgment", "market_value", "taxes_owed"}
    if sort_by in sortable_fields:
        reverse = sort_dir == "desc"
        results.sort(key=lambda d: (d.get(sort_by) is None, d.get(sort_by)), reverse=reverse)

    total = len(results)
    start = (page - 1) * page_size
    end = start + page_size
    page_results = results[start:end]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "results": page_results,
    }


@app.get("/api/properties/{property_id}")
def get_property(property_id: int, db: Session = Depends(get_db)):
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return _property_to_dict(prop, db)


@app.put("/api/properties/{property_id}")
def update_property(property_id: int, update: PropertyUpdate, db: Session = Depends(get_db)):
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    if update.notes is not None:
        prop.notes = update.notes
    if update.flag_status is not None:
        if update.flag_status not in ("saved", "dismissed", "none"):
            raise HTTPException(status_code=400, detail="flag_status must be saved/dismissed/none")
        prop.flag_status = update.flag_status
    if update.rehab_estimate_user_input is not None:
        prop.rehab_estimate_user_input = update.rehab_estimate_user_input

    db.commit()
    return _property_to_dict(prop, db)


# ---------------------------------------------------------------------------
# Counties endpoints
# ---------------------------------------------------------------------------
@app.get("/api/counties")
def list_counties(db: Session = Depends(get_db)):
    rows = db.query(County).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "region": c.region,
            "platform": c.platform,
            "portal_url": c.portal_url,
            "verified": c.verified,
            "notes": c.notes,
            "last_scraped_at": c.last_scraped_at,
            "last_scrape_success": c.last_scrape_success,
            "last_scrape_error": c.last_scrape_error,
        }
        for c in rows
    ]


# ---------------------------------------------------------------------------
# Scraping endpoints
# ---------------------------------------------------------------------------
NOT_SCRAPED_NOTE = (
    "Fields not shown on the auction listing page (plaintiff, lien priority, "
    "taxes owed, code liens, HOA balance, bankruptcy, flood zone, market "
    "value/comps) are unknown - verify manually before relying on the "
    "composite score."
)


def _json_safe(value):
    """
    Recursively convert a value into something the JSON column can encode -
    datetime -> ISO string, dicts/lists handled recursively. Needed because
    scraped records carry real datetime objects (e.g. parsed sale_date) that
    SQLAlchemy's JSON type cannot serialize directly.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def _upsert_scraped_properties(db: Session, county_name: str, records: List[dict]) -> int:
    """
    Write scraper-extracted records into the Property table. Dedupes on
    (county, case_number) - a re-scrape updates the existing row rather than
    creating a duplicate. Only ever writes fields the scraper actually
    observed; everything else is left null (see NOT_SCRAPED_NOTE) rather
    than fabricated.
    """
    written = 0
    for rec in records:
        case_number = rec.get("case_number")
        if not case_number:
            continue  # can't dedupe/identify a row without a case number

        existing = (
            db.query(Property)
            .filter(Property.county == county_name, Property.case_number == case_number)
            .first()
        )
        prop = existing or Property(county=county_name, case_number=case_number)

        prop.sale_date = rec.get("sale_date")
        prop.address = rec.get("address")
        prop.parcel_id = rec.get("parcel_id")
        prop.final_judgment = rec.get("final_judgment")
        prop.opening_bid = rec.get("opening_bid")
        prop.assessed_value = rec.get("assessed_value")
        prop.source_url = rec.get("source_url")
        prop.raw_scraped_json = _json_safe(rec)
        prop.is_demo_data = False
        prop.last_scraped_at = datetime.utcnow()
        if not prop.notes:
            prop.notes = NOT_SCRAPED_NOTE

        if not existing:
            db.add(prop)
        written += 1

    db.commit()
    return written


def _scrape_one_county(db: Session, county_row: County) -> ScrapeResult:
    scraper_cls = SCRAPER_REGISTRY.get(county_row.platform)
    if not scraper_cls:
        result = ScrapeResult(
            success=False,
            error_message=f"No scraper adapter registered for platform '{county_row.platform}'.",
        )
    else:
        scraper = scraper_cls()
        county_config = {
            "county": county_row.name,
            "portal_url": county_row.portal_url,
            "platform": county_row.platform,
        }
        result = run_scraper_safely(scraper, county_config)
        if result.success and result.records:
            _upsert_scraped_properties(db, county_row.name, result.records)
            _rescore_all(db)

    county_row.last_scraped_at = datetime.utcnow()
    county_row.last_scrape_success = result.success
    county_row.last_scrape_error = result.error_message
    db.commit()

    log = ScrapeLog(
        county=county_row.name,
        timestamp=datetime.utcnow(),
        success=result.success,
        error_message=result.error_message,
        records_found=len(result.records) if result.records else 0,
    )
    db.add(log)
    db.commit()
    return result


@app.post("/api/scrape/{county}")
def scrape_county(county: str, db: Session = Depends(get_db)):
    county_row = db.query(County).filter(County.name == county).first()
    if not county_row:
        raise HTTPException(status_code=404, detail=f"County '{county}' not found")
    try:
        result = _scrape_one_county(db, county_row)
    except Exception as exc:  # belt-and-suspenders; run_scraper_safely already catches
        logger.exception("Unexpected error scraping county %s", county)
        result = ScrapeResult(success=False, error_message=str(exc))
    return {
        "county": county,
        "success": result.success,
        "records_found": len(result.records) if result.records else 0,
        "error_message": result.error_message,
    }


@app.post("/api/scrape/all")
def scrape_all(db: Session = Depends(get_db)):
    counties = db.query(County).all()
    summary = []
    for c in counties:
        try:
            result = _scrape_one_county(db, c)
        except Exception as exc:
            logger.exception("Unexpected error scraping county %s in batch", c.name)
            result = ScrapeResult(success=False, error_message=str(exc))
        summary.append({
            "county": c.name,
            "success": result.success,
            "records_found": len(result.records) if result.records else 0,
            "error_message": result.error_message,
        })
    return {"results": summary}


def _scrape_all_job():
    """Used by the APScheduler daily cron job. Opens its own DB session."""
    db = SessionLocal()
    try:
        counties = db.query(County).all()
        for c in counties:
            try:
                _scrape_one_county(db, c)
            except Exception:
                logger.exception("Scheduled scrape failed for county %s", c.name)
    finally:
        db.close()


@app.get("/api/scrape-status")
def scrape_status(db: Session = Depends(get_db)):
    rows = db.query(County).all()
    return [
        {
            "county": c.name,
            "last_scraped_at": c.last_scraped_at,
            "last_scrape_success": c.last_scrape_success,
            "last_scrape_error": c.last_scrape_error,
        }
        for c in rows
    ]


# ---------------------------------------------------------------------------
# Weights endpoints
# ---------------------------------------------------------------------------
@app.get("/api/weights")
def get_weights(db: Session = Depends(get_db)):
    rows = db.query(ScoreWeight).all()
    return [{"key": r.key, "weight": r.weight, "description": r.description} for r in rows]


@app.put("/api/weights")
def update_weights(update: WeightsUpdate, db: Session = Depends(get_db)):
    for item in update.weights:
        row = db.query(ScoreWeight).filter(ScoreWeight.key == item.key).first()
        if row:
            row.weight = item.weight
        else:
            db.add(ScoreWeight(key=item.key, weight=item.weight, description=WEIGHT_DESCRIPTIONS.get(item.key, "")))
    db.commit()
    _rescore_all(db)
    rows = db.query(ScoreWeight).all()
    return [{"key": r.key, "weight": r.weight, "description": r.description} for r in rows]


# ---------------------------------------------------------------------------
# Export endpoint
# ---------------------------------------------------------------------------
@app.get("/api/export")
def export_properties(
    format: str = Query("csv", pattern="^(csv|xlsx)$"),
    county: Optional[str] = None,
    flag_status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Property)
    if county:
        query = query.filter(Property.county == county)
    if flag_status:
        query = query.filter(Property.flag_status == flag_status)
    rows = query.all()

    records = [_property_to_dict(r, db) for r in rows]
    for r in records:
        r.pop("component_breakdown", None)
        r["warnings"] = "; ".join(r.get("warnings") or [])

    df = pd.DataFrame(records)

    if format == "csv":
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=properties_export.csv"},
        )
    else:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Properties")
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=properties_export.xlsx"},
        )


# ---------------------------------------------------------------------------
# Title search stub
# ---------------------------------------------------------------------------
def title_search_provider(address: str, parcel_id: str) -> dict:
    """
    Swappable provider interface for real title search integrations.
    Suggested providers: DataTree/First American, ATTOM Data, or a local
    county recorder API. This function must only call an external paid
    service when TITLE_SEARCH_API_KEY and TITLE_SEARCH_PROVIDER are both
    configured; otherwise it returns a not_configured stub.
    """
    if not TITLE_SEARCH_API_KEY or not TITLE_SEARCH_PROVIDER:
        return {
            "status": "not_configured",
            "message": (
                "Set TITLE_SEARCH_API_KEY and TITLE_SEARCH_PROVIDER in .env to "
                "enable. Suggested providers: DataTree/First American, ATTOM "
                "Data, or a local county recorder API."
            ),
        }
    # Real provider integration would go here, keyed off TITLE_SEARCH_PROVIDER.
    return {
        "status": "not_implemented",
        "message": f"Provider '{TITLE_SEARCH_PROVIDER}' is configured but no integration code exists yet.",
    }


@app.post("/api/title-search/{property_id}")
def title_search(property_id: int, db: Session = Depends(get_db)):
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return title_search_provider(prop.address, prop.parcel_id)


# ---------------------------------------------------------------------------
# Serve the built frontend (production only).
#
# In local dev, frontend/dist won't exist (you run `npm run dev` on :5173
# instead), so this block is skipped entirely and nothing changes for
# local development. In production (e.g. the Docker image built for
# Railway), the frontend is pre-built into frontend/dist and this mounts
# it at "/", served by the same FastAPI process/port as the API.
#
# All API routes above are already under /api/*, so they always take
# priority over the SPA catch-all below (FastAPI matches routes in
# registration order, and the catch-all is registered last).
# ---------------------------------------------------------------------------
FRONTEND_DIST = _Path(__file__).resolve().parent.parent / "frontend" / "dist"

if FRONTEND_DIST.exists():
    logger.info("Serving frontend from %s", FRONTEND_DIST)

    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIST / "assets")),
        name="frontend-assets",
    )

    @app.get("/favicon.svg", include_in_schema=False)
    def _favicon():
        return FileResponse(str(FRONTEND_DIST / "favicon.svg"))

    @app.get("/icons.svg", include_in_schema=False)
    def _icons():
        return FileResponse(str(FRONTEND_DIST / "icons.svg"))

    @app.get("/{full_path:path}", include_in_schema=False)
    def _spa_catch_all(full_path: str):
        """
        SPA fallback: serve index.html for any non-API, non-static path so
        client-side routing (React Router-style deep links, refreshes on a
        sub-route, etc.) works. /api/* is never reached here because those
        routes are registered above and matched first.
        """
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.exists() and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(FRONTEND_DIST / "index.html"))
else:
    logger.info(
        "frontend/dist not found - skipping static file mount (expected in "
        "local dev; run `npm run build` in frontend/ to produce it)."
    )
