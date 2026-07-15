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
import threading
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

import pandas as pd
from pathlib import Path as _Path

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler

from db import Base, engine, get_db, SessionLocal, ensure_columns
from models import County, Property, ScrapeLog, ScoreWeight, Watchlist, BidRecord
from config import load_counties_config, TITLE_SEARCH_API_KEY, TITLE_SEARCH_PROVIDER
from scrapers.sample_data import seed_sample_data
from scrapers.base import run_scraper_safely, ScrapeResult
from scrapers.realauction_playwright import RealAuctionPlaywrightScraper
from scrapers.grantstreet import GrantStreetScraper
from scrapers.zillow_scraper import get_zillow_estimate
from scrapers.realtor_scraper import get_realtor_estimate
from scrapers.redfin_scraper import get_redfin_estimate
from scrapers.market_conditions import get_market_conditions_and_median_price
from scrapers.crime_scraper import get_crime_grade
from scrapers.flood_zone import get_flood_zone
from scrapers.plaintiff_lookup import lookup_plaintiff, classify_plaintiff_type, get_case_lookup_url
from scoring import compute_score, compute_ranking_score, compute_score_explanation

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
    ensure_columns(engine, Base)  # additive auto-migration, see db.py
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
        _register_scheduler_jobs()
        scheduler.start()
        logger.info(
            "Scheduler started: scrape-all jobs registered for 06:00 and 18:00; "
            "enrich_sweep registered every %d minutes.", ENRICH_SWEEP_INTERVAL_MINUTES,
        )


@app.on_event("shutdown")
def on_shutdown():
    if scheduler.running:
        scheduler.shutdown(wait=False)


def _register_scheduler_jobs():
    """
    Registers the twice-daily scrape-all cron jobs (06:00 and 18:00 per the
    Phase 2 spec: cron `0 6 * * *` / `0 18 * * *`). Split out from
    on_startup() so tests can register jobs against the module-level
    scheduler without going through the rest of the app startup sequence
    (DB seeding, demo data, etc.) - see tests/test_scheduler.py.
    """
    scheduler.add_job(
        scrape_all_counties,
        "cron",
        hour=6,
        minute=0,
        id="scrape_all_6am",
        replace_existing=True,
    )
    scheduler.add_job(
        scrape_all_counties,
        "cron",
        hour=18,
        minute=0,
        id="scrape_all_6pm",
        replace_existing=True,
    )
    # Phase 2c (2026-07-15): background enrich-sweep so investors see
    # estimated value / profit gap numbers on the dashboard without having
    # to open each property's detail page first (which is what previously
    # triggered enrichment). Runs every ENRICH_SWEEP_INTERVAL_MINUTES,
    # bounded to ENRICH_SWEEP_BATCH_SIZE properties per tick so it never
    # turns into an unbounded background hammering of Zillow/Realtor.com/
    # Redfin - same "polite, rate-limited" intent as the county scrapers.
    scheduler.add_job(
        enrich_sweep,
        "interval",
        minutes=ENRICH_SWEEP_INTERVAL_MINUTES,
        id="enrich_sweep",
        replace_existing=True,
    )


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
        # Phase 2: 0-100 investor-facing ranking - 50% deal quality (real
        # Zillow/Realtor.com/Redfin estimates vs. final judgment) + 50%
        # risk (lien priority, bankruptcy, taxes, code liens, flood,
        # crime). Falls back to risk-only if no estimates are populated
        # yet (see scoring.compute_ranking_score).
        prop.ranking_score = compute_ranking_score(prop, weights)
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


class NotesUpdate(BaseModel):
    investor_notes: str


class WeightUpdateItem(BaseModel):
    key: str
    weight: float


class WeightsUpdate(BaseModel):
    weights: List[WeightUpdateItem]


class BidRecordCreate(BaseModel):
    property_id: int
    bid_amount: Optional[float] = None
    sale_price: Optional[float] = None
    winner: Optional[str] = None
    notes: Optional[str] = None


def _watchlisted_ids(db: Session) -> set:
    return {w.property_id for w in db.query(Watchlist.property_id).all()}


def _property_to_dict(prop: Property, db: Session) -> dict:
    weights = _get_weights_dict(db)
    score = compute_score(prop, weights)
    is_watchlisted = db.query(Watchlist).filter(Watchlist.property_id == prop.id).first() is not None
    days_to_auction = None
    if prop.sale_date:
        days_to_auction = (prop.sale_date.date() - datetime.utcnow().date()).days
    _score_explanation = compute_score_explanation(prop)
    _profit = _score_explanation.get("profit") or {}
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
        # Phase 6 (2026-07-15)
        "plaintiff_source": prop.plaintiff_source,
        "case_lookup_url": prop.case_lookup_url,
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
        "investor_notes": prop.investor_notes,
        "flag_status": prop.flag_status,
        "source_url": prop.source_url,
        "is_demo_data": prop.is_demo_data,
        "last_scraped_at": prop.last_scraped_at,
        "auction_status": prop.auction_status,
        "cancellation_reason": prop.cancellation_reason,
        "equity_spread": (prop.market_value or 0.0) - (prop.final_judgment or 0.0),
        "composite_score": score["composite_score"],
        "ranking_score": prop.ranking_score,
        "component_breakdown": score["component_breakdown"],
        "warnings": score["warnings"],
        # Phase 4/5 (2026-07-13): profit-first 85/15 formula's full structured
        # breakdown (profit gap math, location components, warnings) so
        # ScoreExplainer.jsx can show the investor the exact numbers the
        # formula used without duplicating it in JS. Computed fresh here
        # (not stored) since it's cheap - no network calls, unlike the
        # legacy compute_score() above which can hit FEMA on a placeholder
        # flood_zone.
        "score_explanation": _score_explanation,
        # Phase 2d (2026-07-15): top-level convenience mirrors of
        # score_explanation["profit"]'s estimated value / profit gap so the
        # dashboard's dense table can show and sort by them as first-class
        # columns without the frontend reaching into the nested breakdown.
        # None whenever the underlying profit calc is None (missing cost
        # basis or missing value data) - never a fabricated number.
        "estimated_value": _profit.get("est_value"),
        "profit_gap_dollars": _profit.get("profit_gap_dollars"),
        "profit_gap_pct": _profit.get("profit_gap_pct"),
        "used_assessed_fallback": _profit.get("used_assessed_fallback"),
        "zillow_estimate": prop.zillow_estimate,
        "realtor_estimate": prop.realtor_estimate,
        "redfin_estimate": prop.redfin_estimate,
        "market_conditions": prop.market_conditions,
        "estimates_last_updated": prop.estimates_last_updated,
        # Phase B (2026-07-13): canonical estimate-site URLs + zip median price
        "zillow_url": prop.zillow_url,
        "realtor_url": prop.realtor_url,
        "redfin_url": prop.redfin_url,
        "zip_median_sale_price": prop.zip_median_sale_price,
        # Phase C (2026-07-13): crime grade, real flood zone lookup, coords
        "crime_grade": prop.crime_grade,
        "crime_grade_source_url": prop.crime_grade_source_url,
        "flood_zone_source": prop.flood_zone_source,
        "latitude": prop.latitude,
        "longitude": prop.longitude,
        "is_watchlisted": is_watchlisted,
        "days_to_auction": days_to_auction,
    }


# ---------------------------------------------------------------------------
# Properties endpoints
# ---------------------------------------------------------------------------
@app.get("/api/properties")
def list_properties(
    county: Optional[str] = None,
    sale_date_from: Optional[date] = None,
    sale_date_to: Optional[date] = None,
    filter: Optional[str] = Query(None, description="Special filter mode. 'by_date' restricts to a single sale_date (requires the `date` param) - used by the calendar view."),
    date: Optional[date] = Query(None, description="Used with filter=by_date, e.g. 2026-07-06"),
    min_equity_spread: Optional[float] = None,
    plaintiff_type: Optional[str] = None,
    occupancy_status: Optional[str] = None,
    flag_status: Optional[str] = None,
    auction_status: Optional[str] = None,
    watchlist_only: bool = False,
    sort_by: str = Query("ranking_score", description="Field to sort by (default: ranking_score, the 0-100 investor-facing rank)"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(Property)
    if county:
        query = query.filter(Property.county == county)
    if filter == "by_date" and date:
        day_start = datetime.combine(date, datetime.min.time())
        day_end = day_start + timedelta(days=1)
        query = query.filter(Property.sale_date >= day_start, Property.sale_date < day_end)
    else:
        if sale_date_from:
            query = query.filter(Property.sale_date >= sale_date_from)
        if sale_date_to:
            query = query.filter(Property.sale_date <= sale_date_to)
    if watchlist_only:
        watchlisted = _watchlisted_ids(db)
        query = query.filter(Property.id.in_(watchlisted)) if watchlisted else query.filter(False)
    if plaintiff_type:
        query = query.filter(Property.plaintiff_type == plaintiff_type)
    if occupancy_status:
        query = query.filter(Property.occupancy_status == occupancy_status)
    if flag_status:
        query = query.filter(Property.flag_status == flag_status)
    if auction_status:
        query = query.filter(Property.auction_status == auction_status)

    rows = query.all()

    if min_equity_spread is not None:
        rows = [r for r in rows if ((r.market_value or 0.0) - (r.final_judgment or 0.0)) >= min_equity_spread]

    results = [_property_to_dict(r, db) for r in rows]

    sortable_fields = {
        "ranking_score", "composite_score", "equity_spread", "sale_date", "final_judgment",
        "market_value", "taxes_owed",
        # Phase 2d (2026-07-15): let the dense table sort by the new
        # first-class estimate/profit-gap columns too.
        "estimated_value", "profit_gap_dollars",
    }
    if sort_by in sortable_fields:
        # Phase 4 (2026-07-13) found and fixed a real bug here: the old
        # `key=lambda d: (d.get(sort_by) is None, ...), reverse=reverse`
        # approach sorts None to the FRONT whenever reverse=True (desc),
        # since reverse=True flips the is-None flag's ordering right along
        # with the value's - the opposite of "unscored properties sort
        # last" (explicit spec, now directly observable since
        # ranking_score can genuinely be null for the first time under the
        # new profit-first formula, whereas the old formula never produced
        # a null and this bug was dormant). Fixed by always appending
        # null-valued rows at the end regardless of sort direction.
        reverse = sort_dir == "desc"
        non_null = [d for d in results if d.get(sort_by) is not None]
        null_valued = [d for d in results if d.get(sort_by) is None]
        non_null.sort(key=lambda d: d.get(sort_by), reverse=reverse)
        results = non_null + null_valued

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


@app.patch("/api/properties/{property_id}/notes")
def patch_property_notes(property_id: int, update: NotesUpdate, db: Session = Depends(get_db)):
    """
    Phase 3: dedicated endpoint for the NotesPad component, which auto-saves
    on blur. Writes to investor_notes (separate from the general `notes`
    field, which the scraper also writes to - see models.Property).
    """
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    prop.investor_notes = update.investor_notes
    db.commit()
    return _property_to_dict(prop, db)


# ---------------------------------------------------------------------------
# Watchlist endpoints (Phase 3)
# ---------------------------------------------------------------------------
@app.get("/api/watchlist")
def get_watchlist(db: Session = Depends(get_db)):
    rows = db.query(Watchlist).order_by(Watchlist.saved_at.desc()).all()
    property_ids = [w.property_id for w in rows]
    if not property_ids:
        return []
    props = db.query(Property).filter(Property.id.in_(property_ids)).all()
    by_id = {p.id: p for p in props}
    # Preserve watchlist order (most recently saved first), skipping any
    # property_id whose Property row has since been deleted.
    return [_property_to_dict(by_id[pid], db) for pid in property_ids if pid in by_id]


@app.post("/api/watchlist/{property_id}")
def add_to_watchlist(property_id: int, db: Session = Depends(get_db)):
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    existing = db.query(Watchlist).filter(Watchlist.property_id == property_id).first()
    if not existing:
        db.add(Watchlist(property_id=property_id, saved_at=datetime.utcnow()))
        db.commit()
    return _property_to_dict(prop, db)


@app.delete("/api/watchlist/{property_id}")
def remove_from_watchlist(property_id: int, db: Session = Depends(get_db)):
    existing = db.query(Watchlist).filter(Watchlist.property_id == property_id).first()
    if existing:
        db.delete(existing)
        db.commit()
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        return {"property_id": property_id, "is_watchlisted": False}
    return _property_to_dict(prop, db)


# ---------------------------------------------------------------------------
# Bid record endpoints (Phase 3) - manual investor-entered auction outcomes
# ---------------------------------------------------------------------------
@app.post("/api/bid-records")
def create_bid_record(record: BidRecordCreate, db: Session = Depends(get_db)):
    prop = db.query(Property).filter(Property.id == record.property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    row = BidRecord(
        property_id=record.property_id,
        bid_amount=record.bid_amount,
        sale_price=record.sale_price,
        winner=record.winner,
        notes=record.notes,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "property_id": row.property_id,
        "bid_amount": row.bid_amount,
        "sale_price": row.sale_price,
        "winner": row.winner,
        "notes": row.notes,
        "created_at": row.created_at,
    }


@app.get("/api/bid-records")
def list_bid_records(property_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(BidRecord)
    if property_id is not None:
        query = query.filter(BidRecord.property_id == property_id)
    rows = query.order_by(BidRecord.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "property_id": r.property_id,
            "bid_amount": r.bid_amount,
            "sale_price": r.sale_price,
            "winner": r.winner,
            "notes": r.notes,
            "created_at": r.created_at,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Property enrichment (Zillow/Realtor.com/Redfin estimates + market
# conditions) - lazy-loaded on demand when the frontend detail page mounts,
# never as part of the batch auction scrapers.
# ---------------------------------------------------------------------------
ENRICH_CACHE_HOURS = 24


def _extract_zip(address: Optional[str]) -> Optional[str]:
    """Best-effort 5-digit zip extraction from a scraped address string,
    e.g. '3402 PEARSON RD VALRICO, FL- 33596' -> '33596'. Returns None if
    the address doesn't end in a recognizable 5-digit zip (never guessed)."""
    if not address:
        return None
    parts = address.strip().split()
    if parts and parts[-1].isdigit() and len(parts[-1]) == 5:
        return parts[-1]
    return None


@app.get("/api/properties/{property_id}/enrich")
def enrich_property(property_id: int, db: Session = Depends(get_db)):
    """
    Calls the Zillow/Realtor.com/Redfin estimate scrapers and the market
    conditions lookup for this property, updates the Property record, and
    returns the enriched property. Results are cached for
    ENRICH_CACHE_HOURS: if estimates_last_updated is recent enough, this
    just returns the cached record without re-scraping (idempotent, and
    polite to the source sites on repeated detail-page visits).

    Each of the four lookups is wrapped individually so a single scraper
    failure (blocked page, site down, playwright not installed, etc.)
    never prevents the other three from updating - failures are collected
    and returned under "enrich_errors" rather than raising, and any
    lookup that can't find a real figure is left null rather than guessed.
    """
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    now = datetime.utcnow()
    if prop.estimates_last_updated and (now - prop.estimates_last_updated) < timedelta(hours=ENRICH_CACHE_HOURS):
        logger.info(
            "Property %d estimates last updated %s (< %dh ago); returning cached values.",
            property_id, prop.estimates_last_updated, ENRICH_CACHE_HOURS,
        )
        result = _property_to_dict(prop, db)
        result["enrich_errors"] = []
        result["enrich_cached"] = True
        return result

    if not prop.address:
        raise HTTPException(status_code=400, detail="Property has no address to enrich against.")

    zip_code = _extract_zip(prop.address)
    errors: List[str] = []

    try:
        zillow_result = get_zillow_estimate(prop.address)
        prop.zillow_estimate = zillow_result.get("estimate")
        prop.zillow_url = zillow_result.get("url")
    except Exception as exc:
        logger.exception("Zillow scraper failed for property %d", property_id)
        errors.append(f"zillow: {exc}")

    try:
        realtor_result = get_realtor_estimate(prop.address)
        prop.realtor_estimate = realtor_result.get("estimate")
        prop.realtor_url = realtor_result.get("url")
    except Exception as exc:
        logger.exception("Realtor.com scraper failed for property %d", property_id)
        errors.append(f"realtor: {exc}")

    try:
        redfin_result = get_redfin_estimate(prop.address)
        prop.redfin_estimate = redfin_result.get("estimate")
        prop.redfin_url = redfin_result.get("url")
    except Exception as exc:
        logger.exception("Redfin scraper failed for property %d", property_id)
        errors.append(f"redfin: {exc}")

    try:
        # Phase B.2: market conditions (buyer's/seller's market) and the
        # zip's median sale price come from one Redfin page fetch.
        market_result = get_market_conditions_and_median_price(zip_code)
        prop.market_conditions = market_result.get("market_conditions")
        prop.zip_median_sale_price = market_result.get("zip_median_sale_price")
    except Exception as exc:
        logger.exception("Market conditions lookup failed for property %d", property_id)
        errors.append(f"market_conditions: {exc}")

    try:
        # Phase C.1: crimegrade.org zip-level crime grade (replaces the
        # never-provisioned FBI Crime Data API key approach).
        crime_result = get_crime_grade(zip_code)
        if crime_result:
            prop.crime_grade = crime_result.get("overall") or crime_result.get("violent")
            prop.crime_grade_source_url = crime_result.get("source_url")
        else:
            prop.crime_grade = None
            prop.crime_grade_source_url = None
    except Exception as exc:
        logger.exception("Crime grade lookup failed for property %d", property_id)
        errors.append(f"crime_grade: {exc}")

    try:
        # Phase C.2: real FEMA NFHL flood zone lookup (replaces the
        # always-placeholder previous behavior). Also captures lat/lng so
        # the frontend can link out to the USFWS Wetlands Mapper centered
        # on this property.
        flood_result = get_flood_zone(prop.address)
        prop.flood_zone = flood_result.get("flood_zone")
        prop.flood_zone_source = flood_result.get("source")
        prop.latitude = flood_result.get("latitude")
        prop.longitude = flood_result.get("longitude")
    except Exception as exc:
        logger.exception("Flood zone lookup failed for property %d", property_id)
        errors.append(f"flood_zone: {exc}")

    try:
        # Phase 6 (2026-07-15): who's foreclosing. Only re-looked-up if we
        # don't already have a plaintiff_name (case style never changes
        # once filed, so there's no reason to re-hit the clerk site on
        # every /enrich re-run the way estimates need refreshing).
        if not prop.plaintiff_name:
            plaintiff_result = lookup_plaintiff(prop.county, prop.case_number)
            plaintiff_name = plaintiff_result.get("plaintiff_name")
            if plaintiff_name:
                prop.plaintiff_name = plaintiff_name
                prop.plaintiff_source = plaintiff_result.get("plaintiff_source")
                prop.plaintiff_type = classify_plaintiff_type(plaintiff_name)
            # case_lookup_url is worth keeping current even when no name
            # was resolved, so the UI always has a real link-out.
            prop.case_lookup_url = plaintiff_result.get("case_lookup_url") or prop.case_lookup_url
    except Exception as exc:
        logger.exception("Plaintiff lookup failed for property %d", property_id)
        errors.append(f"plaintiff_lookup: {exc}")

    prop.estimates_last_updated = now

    # Phase 2: recompute composite_score/ranking_score right away so the
    # newly-fetched estimates are reflected immediately, rather than
    # waiting for the next scheduled _rescore_all() pass.
    weights = _get_weights_dict(db)
    prop.composite_score = compute_score(prop, weights)["composite_score"]
    prop.ranking_score = compute_ranking_score(prop, weights)

    db.commit()

    result = _property_to_dict(prop, db)
    result["enrich_errors"] = errors
    result["enrich_cached"] = False
    return result


ENRICH_SWEEP_BATCH_SIZE = 15
ENRICH_SWEEP_INTERVAL_MINUTES = 30
_enrich_sweep_lock = threading.Lock()


def enrich_sweep():
    """
    Phase 2c (2026-07-15) background job (see _register_scheduler_jobs).

    Proactively runs the same enrich_property() logic (Zillow/Realtor.com/
    Redfin estimates + crime/flood/market-conditions) against upcoming
    properties that have never been enriched, or whose estimates are
    stale (older than ENRICH_CACHE_HOURS) - so the dashboard's Est. Value /
    Profit Gap columns (Phase 2d) are populated without an investor having
    to open every single detail page first.

    Design notes:
    - Only considers properties with a future sale_date and a real address
      - no point spending a Zillow/Redfin request budget on an auction
        that's already happened or one we can't even resolve an address
        for.
    - Bounded to ENRICH_SWEEP_BATCH_SIZE per tick, ordered oldest-enriched
      (or never-enriched) first, so a large backlog drains gradually over
      many ticks instead of firing a big burst of requests at once.
    - Non-reentrant (_enrich_sweep_lock): if a previous sweep is still
      running when the next interval fires, this tick is skipped rather
      than piling up concurrent sweeps.
    - Same never-fabricate contract as the on-demand endpoint: a property
      whose scrapers all fail (bot-blocked, no match, etc.) just keeps its
      existing null estimate fields - errors are logged, never guessed
      around.
    """
    if not _enrich_sweep_lock.acquire(blocking=False):
        logger.info("enrich_sweep: a previous sweep is still running; skipping this tick.")
        return
    try:
        db = SessionLocal()
        try:
            cutoff = datetime.utcnow() - timedelta(hours=ENRICH_CACHE_HOURS)
            candidates = (
                db.query(Property)
                .filter(Property.sale_date.isnot(None))
                .filter(Property.sale_date >= datetime.utcnow())
                .filter(Property.address.isnot(None))
                .filter(
                    (Property.estimates_last_updated.is_(None))
                    | (Property.estimates_last_updated < cutoff)
                )
                # SQLite sorts NULLs first on ASC by default, which is what
                # we want here: never-enriched properties take priority
                # over ones that are merely stale.
                .order_by(Property.estimates_last_updated.asc())
                .limit(ENRICH_SWEEP_BATCH_SIZE)
                .all()
            )
            if not candidates:
                logger.info("enrich_sweep: no properties due for enrichment this tick.")
                return
            logger.info("enrich_sweep: enriching %d propert(y/ies).", len(candidates))
            for prop in candidates:
                try:
                    enrich_property(prop.id, db)
                except Exception:
                    logger.exception("enrich_sweep: failed to enrich property %d", prop.id)
        finally:
            db.close()
    finally:
        _enrich_sweep_lock.release()


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


def _upsert_scraped_properties(db: Session, county_name: str, records: List[dict]) -> Dict[str, int]:
    """
    Write scraper-extracted records into the Property table. Dedupes on
    (county, case_number) - a re-scrape updates the existing row rather than
    creating a duplicate. Only ever writes fields the scraper actually
    observed; everything else is left null (see NOT_SCRAPED_NOTE) rather
    than fabricated.

    Returns {"new": n, "updated": n} so the caller can log a real count of
    what changed in this run (see ScrapeLog.new_count / .canceled_count),
    rather than just a single opaque "records_found" total.
    """
    new_count = 0
    updated_count = 0
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

        is_canceled = rec.get("auction_status") == "canceled"

        # 2026-07-06: a record scraped from RealAuction's #Area_C
        # ("Auctions Closed or Canceled") section never has a sale
        # date/time on the page - only a status reason - so don't let a
        # canceled record null out a sale_date we already knew from a
        # previous active scrape of the same case number. An active
        # record's sale_date always overwrites, same as before.
        if not (is_canceled and rec.get("sale_date") is None):
            prop.sale_date = rec.get("sale_date")
        prop.address = rec.get("address")
        prop.parcel_id = rec.get("parcel_id")
        prop.final_judgment = rec.get("final_judgment")
        prop.opening_bid = rec.get("opening_bid")
        prop.assessed_value = rec.get("assessed_value")
        prop.source_url = rec.get("source_url")
        prop.raw_scraped_json = _json_safe(rec)
        if not prop.case_lookup_url:
            # Phase 6 (2026-07-15): populate the clerk case-search link-out
            # immediately at scrape time (not just after /enrich runs) so
            # every property has somewhere real to check by hand right
            # away, even before the enrich sweep has ever touched it.
            prop.case_lookup_url = get_case_lookup_url(county_name)
        prop.is_demo_data = False
        prop.last_scraped_at = datetime.utcnow()
        if is_canceled:
            # The source site explicitly shows this as closed/canceled with
            # a stated reason - trust that directly rather than only ever
            # inferring cancellation from a case number disappearing (see
            # _mark_missing_auctions_canceled below, which is now purely a
            # fallback for cases removed from the site entirely with no
            # reason ever shown).
            prop.auction_status = "canceled"
            prop.cancellation_reason = rec.get("cancellation_reason")
        else:
            # Reappearing as an active listing in a fresh scrape means it's
            # active again, even if a prior run had marked it canceled
            # (e.g. a postponed sale later rescheduled and republished
            # under the same case #) - clear any stale reason from before.
            prop.auction_status = "active"
            prop.cancellation_reason = None
        if not prop.notes:
            prop.notes = NOT_SCRAPED_NOTE

        if not existing:
            db.add(prop)
            new_count += 1
        else:
            updated_count += 1

    db.commit()
    return {"new": new_count, "updated": updated_count}


def _mark_missing_auctions_canceled(db: Session, county_name: str, scraped_case_numbers: set) -> int:
    """
    Compares the latest successful scrape's case numbers against existing
    Property rows for this county. Any row that: (a) is real (not demo
    data), (b) isn't already marked canceled, (c) has a sale_date that
    hasn't happened yet (or no sale_date at all), and (d) did NOT show up
    in this scrape - gets marked auction_status="canceled".

    Deliberately conservative: a sale with a sale_date in the past is left
    alone (it already happened or the calendar rolled past it - that's not
    the same thing as "canceled"), and demo data is never touched. Returns
    the number of rows marked, for ScrapeLog.canceled_count.
    """
    now = datetime.utcnow()
    candidates = (
        db.query(Property)
        .filter(Property.county == county_name)
        .filter(Property.is_demo_data.is_(False))
        .filter(Property.auction_status != "canceled")
        .all()
    )
    marked = 0
    for prop in candidates:
        if not prop.case_number or prop.case_number in scraped_case_numbers:
            continue
        if prop.sale_date is not None and prop.sale_date < now:
            continue  # already happened - historical, not "canceled"
        prop.auction_status = "canceled"
        marked += 1

    if marked:
        db.commit()
    return marked


def _scrape_one_county(db: Session, county_row: County) -> ScrapeResult:
    scraper_cls = SCRAPER_REGISTRY.get(county_row.platform)
    new_count = 0
    canceled_count = 0

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
            upsert_stats = _upsert_scraped_properties(db, county_row.name, result.records)
            new_count = upsert_stats["new"]

            scraped_case_numbers = {
                r.get("case_number") for r in result.records if r.get("case_number")
            }
            canceled_count = _mark_missing_auctions_canceled(db, county_row.name, scraped_case_numbers)
            if canceled_count:
                logger.info(
                    "Marked %d auction(s) canceled in %s (no longer present in latest scrape).",
                    canceled_count, county_row.name,
                )
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
        new_count=new_count,
        canceled_count=canceled_count,
    )
    db.add(log)
    db.commit()
    return result


# Phase 1 (2026-07-13): "Update All Counties" dashboard button needs (a) a
# guard against two full-batch scrapes running at once (this endpoint scrapes
# counties one at a time in a for-loop, so it never itself exceeds the
# "max 2 concurrent" guardrail - but nothing previously stopped a second
# POST /api/scrape/all from starting mid-run, e.g. a double-click or the
# 06:00/18:00 scheduled job firing while a manual run is still in progress,
# which would hit the same sites twice at once) and (b) progress the
# frontend can poll instead of blocking on this endpoint's response, since a
# full pass across all 14 counties (each up to 45 lookahead days,
# rate-limited) can take several minutes. `_scrape_all_lock` is a plain
# threading.Lock (not asyncio) because these are sync def routes, which
# FastAPI/Starlette run in a worker thread pool - a plain Lock is the
# correct primitive there. `_scrape_all_state` is read by GET
# /api/scrape-status below; it's process-local (not persisted to the DB),
# which is fine since progress-polling only needs to work within the
# lifetime of one running batch on one process.
_scrape_all_lock = threading.Lock()
_scrape_all_state: Dict[str, object] = {
    "running": False,
    "total": 0,
    "completed": 0,
    "last_county": None,
    "last_count": None,
    "started_at": None,
    "finished_at": None,
}


@app.post("/api/scrape/all")
def scrape_all(db: Session = Depends(get_db)):
    # REAL VERIFICATION LOG (2026-07-05): this route MUST be registered
    # before POST /api/scrape/{county} below. Confirmed live in production
    # that with the reverse order (as this file had until now),
    # `POST /api/scrape/all` was silently swallowed by the `{county}` path
    # param route matching literal "all" as a county name, which doesn't
    # exist in the `counties` table -> raised HTTPException(404,
    # "County 'all' not found") -> logged as a bare "404 Not Found" with no
    # indication of the real cause. This is the actual reason the other 13
    # counties never got their first scrape: the only thing that ever
    # called scrape_all_counties() successfully was the scheduled
    # 06:00/18:00 APScheduler job, which calls that Python function
    # directly rather than going through this HTTP route - so a manual
    # "scrape everything now" trigger via this endpoint has been broken
    # since it was added, and would 404 immediately with no useful data
    # written. FastAPI/Starlette match path routes in registration order,
    # so the fix is simply defining the exact-literal route first.
    if not _scrape_all_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail=(
                "A full county scrape is already in progress. Check "
                "GET /api/scrape-status for live progress rather than "
                "starting another one."
            ),
        )
    try:
        counties = db.query(County).all()
        _scrape_all_state.update({
            "running": True,
            "total": len(counties),
            "completed": 0,
            "last_county": None,
            "last_count": None,
            "started_at": datetime.utcnow().isoformat(),
            "finished_at": None,
        })
        summary = []
        for c in counties:
            try:
                result = _scrape_one_county(db, c)
            except Exception as exc:
                logger.exception("Unexpected error scraping county %s in batch", c.name)
                result = ScrapeResult(success=False, error_message=str(exc))
            records_found = len(result.records) if result.records else 0
            summary.append({
                "county": c.name,
                "success": result.success,
                "records_found": records_found,
                "error_message": result.error_message,
            })
            _scrape_all_state["completed"] += 1
            _scrape_all_state["last_county"] = c.name
            _scrape_all_state["last_count"] = records_found
        return {"results": summary}
    finally:
        _scrape_all_state["running"] = False
        _scrape_all_state["finished_at"] = datetime.utcnow().isoformat()
        _scrape_all_lock.release()


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


def scrape_all_counties():
    """
    The twice-daily (06:00 / 18:00) scheduled job body - see
    _register_scheduler_jobs(). Also callable directly (used by tests and
    for a manual "run it now" trigger). Opens its own DB session since
    APScheduler jobs run outside the FastAPI request/response cycle.

    Scrapes every county via _scrape_one_county(), which already handles:
    upserting new/updated auctions, marking auctions missing from the
    latest scrape as canceled, and logging the outcome to scrape_logs.
    Each county is wrapped in its own try/except here too (belt-and-
    suspenders on top of run_scraper_safely) so one county's unexpected
    failure can never abort the rest of the batch.

    Shares `_scrape_all_lock` with POST /api/scrape/all (Phase 1, 2026-07-13)
    so the scheduled run and a manual "Update All Counties" click can never
    overlap and hit the same sites twice at once. If the lock is already
    held (a manual run is in progress), this scheduled run is skipped
    entirely rather than queued or run in parallel - the next scheduled
    slot (or a manual retry) will pick up anything this skip missed.
    """
    if not _scrape_all_lock.acquire(blocking=False):
        logger.warning(
            "Skipping scheduled scrape_all_counties() run - a scrape is "
            "already in progress (manual 'Update All Counties' likely)."
        )
        return
    db = SessionLocal()
    try:
        counties = db.query(County).all()
        _scrape_all_state.update({
            "running": True,
            "total": len(counties),
            "completed": 0,
            "last_county": None,
            "last_count": None,
            "started_at": datetime.utcnow().isoformat(),
            "finished_at": None,
        })
        for c in counties:
            try:
                result = _scrape_one_county(db, c)
                records_found = len(result.records) if result and result.records else 0
            except Exception:
                logger.exception("Scheduled scrape failed for county %s", c.name)
                records_found = 0
            _scrape_all_state["completed"] += 1
            _scrape_all_state["last_county"] = c.name
            _scrape_all_state["last_count"] = records_found
    finally:
        _scrape_all_state["running"] = False
        _scrape_all_state["finished_at"] = datetime.utcnow().isoformat()
        db.close()
        _scrape_all_lock.release()


@app.get("/api/scrape-status")
def scrape_status(db: Session = Depends(get_db)):
    rows = db.query(County).all()
    # Phase 1 (2026-07-13): extended from a bare list to {batch, counties} so
    # the dashboard's "Update All Counties" button can poll batch-in-progress
    # state (X of 14 counties updated, last county + count) in addition to
    # the existing per-county last-scrape info. Nothing else in this repo
    # consumed the old bare-list shape (grepped frontend + tests before
    # making this change), so this isn't a breaking change in practice.
    return {
        "batch": dict(_scrape_all_state),
        "counties": [
            {
                "county": c.name,
                "last_scraped_at": c.last_scraped_at,
                "last_scrape_success": c.last_scrape_success,
                "last_scrape_error": c.last_scrape_error,
            }
            for c in rows
        ],
    }


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
        r.pop("score_explanation", None)
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
# CSV export with selectable columns (Phase 3) - distinct from the existing
# /api/export (which always exports every column, csv or xlsx). The Phase 3
# spec calls specifically for GET /api/export/csv?columns=rank,county,... so
# the frontend can present column checkboxes rather than an all-or-nothing
# dump. Kept alongside the original /api/export rather than replacing it, so
# nothing that already links to /api/export breaks.
# ---------------------------------------------------------------------------
EXPORT_COLUMN_ALIASES = {
    "rank": "ranking_score",
    "judgment": "final_judgment",
}


@app.get("/api/export/csv")
def export_csv_columns(
    columns: Optional[str] = Query(None, description="Comma-separated list of column names to include, e.g. rank,county,address,judgment. Defaults to a sensible standard set if omitted."),
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

    default_columns = [
        "ranking_score", "county", "address", "sale_date", "final_judgment",
        "opening_bid", "equity_spread", "auction_status", "flag_status",
    ]
    if columns:
        requested = [c.strip() for c in columns.split(",") if c.strip()]
        requested = [EXPORT_COLUMN_ALIASES.get(c, c) for c in requested]
    else:
        requested = default_columns

    df = pd.DataFrame(records)
    available = [c for c in requested if c in df.columns]
    missing = [c for c in requested if c not in df.columns]
    if not available:
        raise HTTPException(status_code=400, detail=f"None of the requested columns exist. Unknown: {missing}")
    df = df[available]

    buf = io.StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    headers = {"Content-Disposition": "attachment; filename=properties_export.csv"}
    if missing:
        headers["X-Unknown-Columns"] = ",".join(missing)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers=headers)


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
