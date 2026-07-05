"""
models.py - SQLAlchemy ORM models for the Florida Foreclosure Auction
Analysis & Ranking Tool.
"""
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text, JSON
)

from db import Base


class County(Base):
    __tablename__ = "counties"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    region = Column(String)
    platform = Column(String)  # realforeclose | realtaxdeed | grantstreet_clerkauction | unknown
    portal_url = Column(String)
    verified = Column(Boolean, default=False)
    notes = Column(Text)
    last_scraped_at = Column(DateTime)
    last_scrape_success = Column(Boolean)
    last_scrape_error = Column(Text)


class Property(Base):
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_number = Column(String)
    county = Column(String, index=True)
    sale_date = Column(DateTime)
    owner_name = Column(String)
    address = Column(String)
    parcel_id = Column(String)
    legal_description = Column(Text)
    property_type = Column(String)
    beds = Column(Integer)
    baths = Column(Float)
    sqft = Column(Integer)
    year_built = Column(Integer)

    final_judgment = Column(Float)
    opening_bid = Column(Float)
    assessed_value = Column(Float)
    market_value = Column(Float)

    plaintiff_name = Column(String)
    plaintiff_type = Column(String)  # bank/servicer/HOA-COA/tax_cert/private_lender/other

    occupancy_status = Column(String)
    lien_priority_status = Column(String)
    senior_lien_survives = Column(Boolean, default=False)

    taxes_owed = Column(Float)
    code_liens = Column(Float)
    flood_zone = Column(String)
    insurance_estimate = Column(Float)
    comps_json = Column(JSON)

    bankruptcy_flag = Column(Boolean, default=False)
    redemption_notes = Column(Text)
    hoa_balance = Column(Float)
    rehab_estimate_user_input = Column(Float)

    notes = Column(Text)
    flag_status = Column(String, default="none")  # saved/dismissed/none

    source_url = Column(String)
    raw_scraped_json = Column(JSON)
    is_demo_data = Column(Boolean, default=False)
    last_scraped_at = Column(DateTime)

    # Phase 2: lifecycle status of the auction itself (distinct from
    # flag_status, which is the investor's own saved/dismissed workflow
    # state). Set to "active" on every successful scrape that (re-)finds
    # this case_number, and flipped to "canceled" by the twice-daily
    # scheduled scrape when a previously-active, not-yet-occurred auction
    # no longer appears in the source county calendar. Never fabricated -
    # only ever set from an actual scrape comparison, never guessed.
    auction_status = Column(String, default="active")  # active | canceled

    # Score fields
    equity_spread = Column(Float)
    composite_score = Column(Float)
    ranking_score = Column(Float)

    # Third-party value estimates (Phase 1: fetched on-demand via
    # GET /api/properties/{id}/enrich, never fabricated - null until a
    # scraper actually returns a real figure). estimates_last_updated
    # gates re-scraping so the enrich endpoint only hits these sites again
    # once the cached estimates are more than 24h old.
    zillow_estimate = Column(Float)
    realtor_estimate = Column(Float)
    redfin_estimate = Column(Float)
    market_conditions = Column(String)  # "buyer_market" | "seller_market" | None
    estimates_last_updated = Column(DateTime)


class ScrapeLog(Base):
    __tablename__ = "scrape_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    county = Column(String, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    success = Column(Boolean)
    error_message = Column(Text)
    records_found = Column(Integer)
    # Phase 2: breakdown of what changed in this scrape run, so
    # "log all changes to scrape_logs" is more than just a pass/fail flag.
    new_count = Column(Integer, default=0)
    canceled_count = Column(Integer, default=0)


class ScoreWeight(Base):
    __tablename__ = "score_weights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String, unique=True, nullable=False)
    weight = Column(Float, nullable=False)
    description = Column(Text)
