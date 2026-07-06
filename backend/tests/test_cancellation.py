"""
test_cancellation.py - tests for how canceled auctions (RealAuction's
#Area_C "Auctions Closed or Canceled" section) are reflected in the app,
per investor feedback (2026-07-06): a canceled auction must not just
disappear or show a bare "canceled" label - the actual reason the county
site gives should be shown.

Covers main._upsert_scraped_properties()'s handling of a record the
scraper marks auction_status="canceled" (see
scrapers/realauction_playwright.py's _build_record): the reason must be
stored, the property must not be deleted, and a canceled record's lack of
a sale_date must never clobber a sale_date already known from a previous
active scrape of the same case number.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime

import main
from db import Base
from models import Property


def _isolated_session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


def test_canceled_record_sets_reason_and_status_without_deleting_row():
    SessionFactory = _isolated_session_factory()
    db = SessionFactory()

    canceled_record = {
        "county": "Hillsborough",
        "case_number": "292024CA005466A001HC",
        "address": "520 SERENITY MILL LOOP RUSKIN, FL- 33570",
        "final_judgment": 230163.86,
        "assessed_value": 306732.0,
        "source_url": "https://hillsborough.realforeclose.com/index.cfm?...",
        "auction_status": "canceled",
        "cancellation_reason": "Canceled per County",
        "sale_date": None,
        "raw_fields": {},
    }

    stats = main._upsert_scraped_properties(db, "Hillsborough", [canceled_record])
    assert stats["new"] == 1

    prop = db.query(Property).filter(Property.case_number == "292024CA005466A001HC").first()
    assert prop is not None  # never deleted - just marked canceled
    assert prop.auction_status == "canceled"
    assert prop.cancellation_reason == "Canceled per County"
    assert prop.final_judgment == 230163.86


def test_canceled_record_does_not_clobber_previously_known_sale_date():
    SessionFactory = _isolated_session_factory()
    db = SessionFactory()

    active_record = {
        "county": "Hillsborough",
        "case_number": "292024CA001637A001HC",
        "address": "3402 PEARSON RD VALRICO, FL- 33596",
        "final_judgment": 216465.96,
        "source_url": "https://hillsborough.realforeclose.com/index.cfm?AUCTIONDATE=07/20/2026",
        "auction_status": "active",
        "cancellation_reason": None,
        "sale_date": datetime(2026, 7, 20, 10, 0),
        "raw_fields": {},
    }
    main._upsert_scraped_properties(db, "Hillsborough", [active_record])

    prop = db.query(Property).filter(Property.case_number == "292024CA001637A001HC").first()
    assert prop.sale_date == datetime(2026, 7, 20, 10, 0)

    # Same case number reappears later in #Area_C (canceled) - the page no
    # longer shows a sale date/time for it (that's expected, see
    # _build_record's docstring), but the previously-scraped sale_date must
    # be preserved, not nulled out.
    canceled_record = {
        "county": "Hillsborough",
        "case_number": "292024CA001637A001HC",
        "address": "3402 PEARSON RD VALRICO, FL- 33596",
        "final_judgment": 216465.96,
        "source_url": "https://hillsborough.realforeclose.com/index.cfm?...",
        "auction_status": "canceled",
        "cancellation_reason": "Canceled per Plaintiff",
        "sale_date": None,
        "raw_fields": {},
    }
    main._upsert_scraped_properties(db, "Hillsborough", [canceled_record])

    db.refresh(prop)
    assert prop.auction_status == "canceled"
    assert prop.cancellation_reason == "Canceled per Plaintiff"
    assert prop.sale_date == datetime(2026, 7, 20, 10, 0)  # preserved, not nulled


def test_case_reappearing_as_active_clears_stale_cancellation_reason():
    SessionFactory = _isolated_session_factory()
    db = SessionFactory()

    canceled_record = {
        "county": "Hillsborough",
        "case_number": "292024CA009999A001HC",
        "final_judgment": 100000.0,
        "source_url": "https://example.com",
        "auction_status": "canceled",
        "cancellation_reason": "Canceled per County",
        "sale_date": None,
        "raw_fields": {},
    }
    main._upsert_scraped_properties(db, "Hillsborough", [canceled_record])

    # A postponed sale later gets rescheduled and republished as active
    # under the same case number - the stale reason must be cleared, not
    # left showing next to an "active" status.
    active_record = {
        "county": "Hillsborough",
        "case_number": "292024CA009999A001HC",
        "final_judgment": 100000.0,
        "source_url": "https://example.com",
        "auction_status": "active",
        "cancellation_reason": None,
        "sale_date": datetime(2026, 8, 1, 10, 0),
        "raw_fields": {},
    }
    main._upsert_scraped_properties(db, "Hillsborough", [active_record])

    prop = db.query(Property).filter(Property.case_number == "292024CA009999A001HC").first()
    assert prop.auction_status == "active"
    assert prop.cancellation_reason is None
