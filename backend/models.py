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

    # Score fields
    equity_spread = Column(Float)
    composite_score = Column(Float)


class ScrapeLog(Base):
    __tablename__ = "scrape_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    county = Column(String, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    success = Column(Boolean)
    error_message = Column(Text)
    records_found = Column(Integer)


class ScoreWeight(Base):
    __tablename__ = "score_weights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String, unique=True, nullable=False)
    weight = Column(Float, nullable=False)
    description = Column(Text)
