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
