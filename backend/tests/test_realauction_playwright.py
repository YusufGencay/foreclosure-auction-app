"""
Unit tests for the pure parsing logic in scrapers/realauction_playwright.py,
using real field values captured from a live (logged-out) browser session
against hillsborough.realforeclose.com on 2026-07-04 (see that module's
docstring for the full verification log).

NOTE ON SCOPE: this sandbox cannot launch a real Chromium instance (no root
to install the OS-level deps Playwright's `playwright install-deps` needs),
so the actual page.goto()/eval_on_selector_all() browser-driving code path
is NOT exercised end-to-end here. What IS tested, against real captured
values, is every piece of logic that does NOT require a live browser: money
parsing, date parsing, and the label->field mapping. The browser-driving
path should be smoke-tested once deployed somewhere with real Chromium
support (e.g. the Docker image, which installs Chromium + deps via
`playwright install --with-deps chromium`).
"""
from datetime import datetime

from scrapers.realauction_playwright import (
    LABEL_FIELD_MAP,
    MONEY_FIELDS,
    _build_record,
    _parse_auction_start,
    _parse_money,
)

# Real label/value pairs captured live from one Hillsborough auction item
# (case 292024CA001637A001HC, 07/20/2026 docket).
REAL_PAIRS = [
    ("Auction Type:", "FORECLOSURE"),
    ("Case #:", "292024CA001637A001HC"),
    ("Final Judgment Amount:", "$216,465.96"),
    ("Parcel ID:", "213008ZZZ000004309900U"),
    ("Property Address:", "3402 PEARSON RD VALRICO, FL- 33596"),
    ("Assessed Value:", "$80,960.00"),
    ("Plaintiff Max Bid:", "Hidden"),
]


def test_parse_money_real_values():
    assert _parse_money("$216,465.96") == 216465.96
    assert _parse_money("$80,960.00") == 80960.00


def test_parse_money_hidden_is_none_not_zero():
    # "Hidden" must never be silently coerced to 0.0 - that would fabricate
    # a max-bid figure that was never actually disclosed.
    assert _parse_money("Hidden") is None


def test_parse_money_empty_and_none():
    assert _parse_money("") is None
    assert _parse_money(None) is None


def test_parse_auction_start_real_value():
    dt = _parse_auction_start("07/20/2026 10:00 AM ET")
    assert dt == datetime(2026, 7, 20, 10, 0)


def test_parse_auction_start_unparseable_is_none():
    assert _parse_auction_start("garbage") is None
    assert _parse_auction_start(None) is None


def test_label_mapping_extracts_known_fields():
    record = {"raw_fields": {}}
    for lbl, val in REAL_PAIRS:
        field = LABEL_FIELD_MAP.get(lbl)
        if field:
            record[field] = _parse_money(val) if field in MONEY_FIELDS else val
        else:
            record["raw_fields"][lbl] = val

    assert record["case_number"] == "292024CA001637A001HC"
    assert record["final_judgment"] == 216465.96
    assert record["parcel_id"] == "213008ZZZ000004309900U"
    assert record["address"] == "3402 PEARSON RD VALRICO, FL- 33596"
    assert record["assessed_value"] == 80960.00
    assert record["plaintiff_max_bid_raw"] == "Hidden"
    assert record["raw_fields"] == {}  # every real label above is mapped


def test_unknown_label_falls_through_to_raw_fields():
    record = {"raw_fields": {}}
    for lbl, val in [("Some New Field:", "surprise value")]:
        field = LABEL_FIELD_MAP.get(lbl)
        if field:
            record[field] = val
        else:
            record["raw_fields"][lbl] = val

    assert record["raw_fields"] == {"Some New Field:": "surprise value"}


# --- _build_record: active vs. canceled items (2026-07-06) ---
#
# Real item captured live from hillsborough.realforeclose.com's #Area_C
# ("Auctions Closed or Canceled" section, 07/10/2026 docket) - confirmed
# these items are NOT dropped/hidden by the site, they carry an explicit
# "Auction Status" / reason (see realauction_playwright.py's REAL
# VERIFICATION LOG). Real active item captured from the same day's
# #Area_W section for comparison.
REAL_CANCELED_ITEM = {
    "_auction_start_raw": "Canceled per County",
    "_status_label": "Auction Status",
    "_aid": "AITEM_1496948",
    "_in_closed_area": True,
    "_pairs": [
        ("Auction Type:", "FORECLOSURE"),
        ("Case #:", "292024CA005466A001HC"),
        ("Final Judgment Amount:", "$230,163.86"),
        ("Parcel ID:", "193218A76000003000230U"),
        ("Property Address:", "520 SERENITY MILL LOOP RUSKIN, FL- 33570"),
        ("Assessed Value:", "$306,732.00"),
        ("Plaintiff Max Bid:", "Hidden"),
    ],
}

REAL_ACTIVE_ITEM = {
    "_auction_start_raw": "07/10/2026 10:00 AM ET",
    "_status_label": "Auction Starts",
    "_aid": "AITEM_1400001",
    "_in_closed_area": False,
    "_pairs": REAL_PAIRS,
}


def test_build_record_canceled_item_captures_reason_not_a_date():
    record = _build_record(REAL_CANCELED_ITEM, "Hillsborough", "https://example.com/day", canceled=True)
    assert record["auction_status"] == "canceled"
    assert record["cancellation_reason"] == "Canceled per County"
    # A reason string must never be mis-parsed as (or fabricated into) a
    # sale date - the source page genuinely doesn't show one here.
    assert record["sale_date"] is None
    assert record["sale_date_raw"] is None
    assert record["case_number"] == "292024CA005466A001HC"
    assert record["final_judgment"] == 230163.86


def test_build_record_active_item_has_no_cancellation_reason():
    record = _build_record(REAL_ACTIVE_ITEM, "Hillsborough", "https://example.com/day", canceled=False)
    assert record["auction_status"] == "active"
    assert record["cancellation_reason"] is None
    assert record["sale_date"] == datetime(2026, 7, 10, 10, 0)
    assert record["case_number"] == "292024CA001637A001HC"
