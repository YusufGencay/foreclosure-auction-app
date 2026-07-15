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
    # Phase 6 (2026-07-15): where plaintiff_name came from, e.g. "clerk case
    # docket (hover.hillsclerk.com)" - shown in the UI next to the derived
    # type so an investor never mistakes an auto-classified guess for a
    # verified fact. Null whenever plaintiff_name itself is null.
    plaintiff_source = Column(String)
    # Best-effort link-out to this property's county clerk case search, so
    # there's always somewhere real to check by hand even when
    # plaintiff_name couldn't be resolved automatically (blocked portal,
    # unsupported county, etc.) - never a guessed URL, see
    # scrapers/plaintiff_lookup.py's CLERK_CASE_SEARCH_URLS.
    case_lookup_url = Column(String)

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

    # Phase 3: dedicated investor notes field, separate from `notes` above
    # (which is populated/overwritten by the scraper with NOT_SCRAPED_NOTE
    # and general free text). investor_notes is only ever written by the
    # investor via PATCH /api/properties/{id}/notes (NotesPad component),
    # so it never gets clobbered by a re-scrape.
    investor_notes = Column(Text)

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

    # 2026-07-06: the reason a canceled auction was canceled, exactly as
    # the county site states it (e.g. "Canceled per County", "Canceled per
    # Plaintiff", "Removed from Sale") - captured only when the source page
    # itself explicitly shows a status/reason (RealAuction's #Area_C
    # "Auctions Closed or Canceled" section, confirmed live to include a
    # literal reason string). Left null when cancellation was only
    # inferred because a case number disappeared from a scrape with no
    # reason ever shown on the source - never fabricated. Cleared back to
    # null if the same case number later reappears as active again.
    cancellation_reason = Column(Text)

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

    # Canonical property-page URLs resolved during the /enrich estimate
    # lookups (Phase B, 2026-07-13) - only ever set when the corresponding
    # scraper actually resolved a real detail-page URL via DuckDuckGo/
    # autocomplete search, never guessed/constructed from the address alone
    # (see estimate_common.resolve_property_url_via_search's docstring for
    # why a guessed URL doesn't work on these sites).
    zillow_url = Column(String)
    realtor_url = Column(String)
    redfin_url = Column(String)

    # Phase 3 (2026-07-15): branded link-out buttons, not scraped estimates
    # (per the user's explicit 2026-07-13 decision - both sites are
    # client-rendered SPAs that don't reliably list every county-courthouse
    # sale, so a scraped "estimate" would be sparse/fragile). Null when no
    # real listing could be resolved - the frontend falls back to each
    # site's homepage, never a guessed deep link.
    federa_url = Column(String)
    auction_com_url = Column(String)

    # Zip-level median sale price (Phase B.2) - scraped from the same
    # Redfin per-zip housing-market page market_conditions.py already
    # fetches for the buyer's/seller's-market classification, so both
    # signals come from one page load rather than two.
    zip_median_sale_price = Column(Float)

    # Location risk data (Phase C, 2026-07-13). Each is null / "unknown -
    # verify manually" until a real lookup succeeds - never fabricated.
    crime_grade = Column(String)  # e.g. "A", "B+", "unknown / verify manually"
    crime_grade_source_url = Column(String)
    latitude = Column(Float)  # geocoded via Census Geocoder (free, no key)
    longitude = Column(Float)
    flood_zone_source = Column(String)  # provenance note for `flood_zone` above

    # Nearby schools (Phase D.2) - list of {name, grade, url} dicts scraped
    # from niche.com when possible; null/empty if niche.com blocked the
    # request, in which case the frontend falls back to a link-out.
    schools_json = Column(JSON)
    schools_source_url = Column(String)


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


class Watchlist(Base):
    """
    Phase 3: investor's saved/tracked properties. Deliberately separate
    from Property.flag_status ("saved"/"dismissed"/"none"), which already
    existed and drives the dashboard filter dropdown - this table is the
    dedicated star/heart "watchlist" concept from the Phase 3 spec, so we
    don't overload flag_status's existing meaning. One row per watched
    property; toggling twice (POST then DELETE) removes it cleanly.
    """
    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    property_id = Column(Integer, nullable=False, unique=True, index=True)
    saved_at = Column(DateTime, default=datetime.utcnow)


class BidRecord(Base):
    """
    Phase 3: a log of an actual (or planned) bid/outcome at auction for a
    property, entered manually by the investor after attending a sale.
    Never auto-populated by a scraper - this is investor-entered history,
    used for tracking outcomes over time (won/lost, price paid vs.
    estimate, etc.).
    """
    __tablename__ = "bid_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    property_id = Column(Integer, nullable=False, index=True)
    bid_amount = Column(Float)
    sale_price = Column(Float)
    winner = Column(String)  # e.g. "us" / "third_party" / "plaintiff" / free text
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
