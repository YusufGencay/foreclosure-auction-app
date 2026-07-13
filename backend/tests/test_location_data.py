"""
test_location_data.py - tests for the Phase C (2026-07-13) location-risk
modules: geocode.py (Census Geocoder), flood_zone.py (FEMA NFHL), and
crime_scraper.py (crimegrade.org). These use plain `requests`, not
Playwright, so they're mocked via monkeypatching requests.get directly
(the same style as test_scrapers.py's Playwright fakes, adapted for the
requests library) rather than a full HTTP server - no real network access
needed to run these.

Also covers market_conditions.py's new zip-median-sale-price extraction
(Phase B.2), added alongside the existing buyer's/seller's-market
classification in the same page fetch.
"""
import pytest

import scrapers.geocode as geocode_mod
import scrapers.flood_zone as flood_zone_mod
import scrapers.crime_scraper as crime_mod
import scrapers.estimate_common as estimate_common
from scrapers.geocode import geocode_address
from scrapers.flood_zone import get_flood_zone, UNKNOWN
from scrapers.crime_scraper import get_crime_grade
from scrapers.market_conditions import get_market_conditions_and_median_price


@pytest.fixture(autouse=True)
def _no_rate_limit_delay(monkeypatch):
    monkeypatch.setattr(estimate_common, "MIN_DELAY_SECONDS", 0)


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        return self._json_data


# --- geocode.py ---

def test_geocode_success(monkeypatch):
    def fake_get(url, params=None, timeout=None, headers=None):
        assert "onelineaddress" in url
        return _FakeResponse(
            200,
            json_data={
                "result": {
                    "addressMatches": [
                        {"coordinates": {"x": -82.297078, "y": 28.133293}}
                    ]
                }
            },
        )

    monkeypatch.setattr(geocode_mod.requests, "get", fake_get)
    result = geocode_address("17915 Saint Croix Isle Dr, Tampa, FL 33647")
    assert result == (28.133293, -82.297078)  # (lat, lng) order, not (x, y)


def test_geocode_no_match(monkeypatch):
    monkeypatch.setattr(
        geocode_mod.requests, "get",
        lambda *a, **kw: _FakeResponse(200, json_data={"result": {"addressMatches": []}}),
    )
    assert geocode_address("Not A Real Address") is None


def test_geocode_http_error(monkeypatch):
    monkeypatch.setattr(geocode_mod.requests, "get", lambda *a, **kw: _FakeResponse(500))
    assert geocode_address("123 Main St") is None


def test_geocode_empty_address_never_makes_request(monkeypatch):
    called = []
    monkeypatch.setattr(geocode_mod.requests, "get", lambda *a, **kw: called.append(1))
    assert geocode_address("") is None
    assert geocode_address(None) is None
    assert called == []


# --- flood_zone.py ---

def test_flood_zone_success(monkeypatch):
    monkeypatch.setattr(flood_zone_mod, "geocode_address", lambda addr: (28.133293, -82.297078))

    def fake_get(url, params=None, timeout=None, headers=None):
        return _FakeResponse(
            200,
            json_data={"features": [{"attributes": {"FLD_ZONE": "AE", "ZONE_SUBTY": "FLOODWAY"}}]},
        )

    monkeypatch.setattr(flood_zone_mod.requests, "get", fake_get)
    result = get_flood_zone("17915 Saint Croix Isle Dr, Tampa, FL 33647")
    assert result["flood_zone"] == "AE"
    assert result["zone_subtype"] == "FLOODWAY"
    assert result["latitude"] == 28.133293
    assert result["longitude"] == -82.297078


def test_flood_zone_no_geocode_match(monkeypatch):
    monkeypatch.setattr(flood_zone_mod, "geocode_address", lambda addr: None)
    result = get_flood_zone("Not A Real Address")
    assert result["flood_zone"] == UNKNOWN
    assert result["latitude"] is None


def test_flood_zone_no_features_returned(monkeypatch):
    monkeypatch.setattr(flood_zone_mod, "geocode_address", lambda addr: (28.0, -82.0))
    monkeypatch.setattr(
        flood_zone_mod.requests, "get",
        lambda *a, **kw: _FakeResponse(200, json_data={"features": []}),
    )
    result = get_flood_zone("123 Main St")
    assert result["flood_zone"] == UNKNOWN
    # Coordinates are still returned even when the zone lookup comes up
    # empty, so the frontend can still link out to the wetlands mapper.
    assert result["latitude"] == 28.0


def test_flood_zone_http_error_never_crashes(monkeypatch):
    monkeypatch.setattr(flood_zone_mod, "geocode_address", lambda addr: (28.0, -82.0))
    monkeypatch.setattr(flood_zone_mod.requests, "get", lambda *a, **kw: _FakeResponse(503))
    result = get_flood_zone("123 Main St")
    assert result["flood_zone"] == UNKNOWN


def test_flood_zone_request_exception_never_crashes(monkeypatch):
    monkeypatch.setattr(flood_zone_mod, "geocode_address", lambda addr: (28.0, -82.0))

    def raise_exc(*a, **kw):
        raise ConnectionError("boom")

    monkeypatch.setattr(flood_zone_mod.requests, "get", raise_exc)
    result = get_flood_zone("123 Main St")
    assert result["flood_zone"] == UNKNOWN


# --- crime_scraper.py ---

_CRIMEGRADE_HTML = """
<html><body>
<h1>33647, FL Violent Crime Rates</h1>
<div>A+</div>
<div>Overall Crime Grade(tm)</div>
<table>
<tr><td>Violent Crime Grade</td><td>A</td></tr>
<tr><td>Property Crime Grade</td><td>A</td></tr>
<tr><td>Other Crime Grade</td><td>A</td></tr>
</table>
</body></html>
"""


def test_crime_grade_success(monkeypatch):
    # Mirrors crimegrade.org's real live layout (confirmed 2026-07-13): the
    # "Overall" grade appears BEFORE its label, while Violent/Property/
    # Other appear AFTER theirs in a table cell - the scraper must handle
    # both orderings.
    monkeypatch.setattr(
        crime_mod.requests, "get",
        lambda *a, **kw: _FakeResponse(200, text=_CRIMEGRADE_HTML),
    )
    result = get_crime_grade("33647")
    assert result["overall"] == "A+"
    assert result["violent"] == "A"
    assert result["property"] == "A"
    assert result["source_url"] == "https://crimegrade.org/violent-crime-33647/"


def test_crime_grade_http_error(monkeypatch):
    monkeypatch.setattr(crime_mod.requests, "get", lambda *a, **kw: _FakeResponse(404, text=""))
    assert get_crime_grade("00000") is None


def test_crime_grade_no_zip_never_makes_request(monkeypatch):
    called = []
    monkeypatch.setattr(crime_mod.requests, "get", lambda *a, **kw: called.append(1))
    assert get_crime_grade("") is None
    assert get_crime_grade(None) is None
    assert called == []


def test_crime_grade_unrecognized_page(monkeypatch):
    monkeypatch.setattr(
        crime_mod.requests, "get",
        lambda *a, **kw: _FakeResponse(200, text="<html><body>Nothing relevant here</body></html>"),
    )
    assert get_crime_grade("33647") is None


# --- market_conditions.py: zip median sale price (Phase B.2) ---

def test_market_conditions_and_median_price_both_found(monkeypatch):
    import scrapers.market_conditions as mc

    monkeypatch.setattr(
        mc, "fetch_page_text",
        lambda url: "Median Sale Price $412,000 ... This is a Seller's Market.",
    )
    result = get_market_conditions_and_median_price("33647")
    assert result["market_conditions"] == "seller_market"
    assert result["zip_median_sale_price"] == 412000.0
    assert result["source_url"] == "https://www.redfin.com/zipcode/33647/housing-market"


def test_market_conditions_found_but_no_median_price(monkeypatch):
    import scrapers.market_conditions as mc

    monkeypatch.setattr(mc, "fetch_page_text", lambda url: "This is a Buyer's Market. No price table here.")
    result = get_market_conditions_and_median_price("33647")
    assert result["market_conditions"] == "buyer_market"
    assert result["zip_median_sale_price"] is None


def test_market_conditions_page_unreachable(monkeypatch):
    import scrapers.market_conditions as mc

    monkeypatch.setattr(mc, "fetch_page_text", lambda url: None)
    result = get_market_conditions_and_median_price("33647")
    assert result["market_conditions"] is None
    assert result["zip_median_sale_price"] is None
