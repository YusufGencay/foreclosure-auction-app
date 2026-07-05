"""
Unit tests for the pure parsing/heuristic logic in scrapers/estimate_common.py
and the label sets used by zillow_scraper.py / realtor_scraper.py /
redfin_scraper.py / market_conditions.py.

Like test_realauction_playwright.py, this sandbox cannot launch a real
Chromium instance or reach these commercial sites, so the actual
Playwright-driven fetch_page_text() browsing path is NOT exercised here.
What IS tested against realistic page-text snippets is every piece of
logic that does NOT require a live browser: dollar-amount extraction near
a label, the bot-block heuristic, and the buyer's/seller's market phrase
match.
"""
from scrapers.estimate_common import _looks_blocked, extract_dollar_amount_near_label
from scrapers.market_conditions import get_market_conditions
from scrapers.zillow_scraper import ZILLOW_LABELS
from scrapers.realtor_scraper import REALTOR_LABELS
from scrapers.redfin_scraper import REDFIN_LABELS


def test_extract_zestimate_from_realistic_snippet():
    text = "3402 Pearson Rd, Valrico, FL 33596\nZestimate®: $412,300\nRent Zestimate: $2,100/mo"
    assert extract_dollar_amount_near_label(text, ZILLOW_LABELS) == 412300.0


def test_extract_redfin_estimate_from_realistic_snippet():
    text = "For sale\nRedfin Estimate $389,450\n3 beds, 2 baths"
    assert extract_dollar_amount_near_label(text, REDFIN_LABELS) == 389450.0


def test_extract_realtor_estimate_from_realistic_snippet():
    text = "Realtor.com Estimate $305,000\nEst. payment $1,900/mo"
    assert extract_dollar_amount_near_label(text, REALTOR_LABELS) == 305000.0


def test_extract_returns_none_when_label_missing():
    assert extract_dollar_amount_near_label("no relevant figure here", ZILLOW_LABELS) is None


def test_extract_returns_none_for_empty_text():
    assert extract_dollar_amount_near_label("", ZILLOW_LABELS) is None
    assert extract_dollar_amount_near_label(None, ZILLOW_LABELS) is None


def test_extract_ignores_small_stray_numbers():
    # A bed/bath count near the label text should never be mistaken for a
    # home value estimate (sanity floor is 1,000).
    text = "Zestimate® $99\n"
    assert extract_dollar_amount_near_label(text, ZILLOW_LABELS) is None


def test_looks_blocked_detects_captcha_page():
    assert _looks_blocked("Please complete the CAPTCHA to continue") is True
    assert _looks_blocked("Are you a robot? Verify to proceed.") is True


def test_looks_blocked_false_for_empty_or_none():
    assert _looks_blocked("") is True
    assert _looks_blocked(None) is True


def test_looks_blocked_false_for_normal_page():
    assert _looks_blocked("Zestimate® $412,300 for this lovely 3 bed 2 bath home") is False


def test_get_market_conditions_returns_none_without_zip(monkeypatch):
    # No network call should even be attempted without a zip code.
    assert get_market_conditions("Hillsborough", "") is None
    assert get_market_conditions("Hillsborough", None) is None


def test_get_market_conditions_parses_seller_market(monkeypatch):
    import scrapers.market_conditions as mc

    monkeypatch.setattr(mc, "fetch_page_text", lambda url: "Market Overview: This is a Seller's Market.")
    assert mc.get_market_conditions("Hillsborough", "33596") == "seller_market"


def test_get_market_conditions_parses_buyer_market(monkeypatch):
    import scrapers.market_conditions as mc

    monkeypatch.setattr(mc, "fetch_page_text", lambda url: "Market Overview: This is a Buyer's Market.")
    assert mc.get_market_conditions("Hillsborough", "33596") == "buyer_market"


def test_get_market_conditions_returns_none_when_unrecognized(monkeypatch):
    import scrapers.market_conditions as mc

    monkeypatch.setattr(mc, "fetch_page_text", lambda url: "Market Overview: figures are mixed this quarter.")
    assert mc.get_market_conditions("Hillsborough", "33596") is None


def test_get_market_conditions_returns_none_when_page_unavailable(monkeypatch):
    import scrapers.market_conditions as mc

    monkeypatch.setattr(mc, "fetch_page_text", lambda url: None)
    assert mc.get_market_conditions("Hillsborough", "33596") is None
