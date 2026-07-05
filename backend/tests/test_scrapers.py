"""
test_scrapers.py - Playwright-mocked success/failure tests for the
on-demand estimate scrapers (zillow/realtor/redfin/market_conditions).

Unlike test_estimate_scrapers.py (which tests the pure parsing/heuristic
helpers in scrapers/estimate_common.py directly), this file mocks
Playwright itself - patching playwright.sync_api.sync_playwright with an
in-memory fake browser/page - so the full fetch_page_text() -> extract
path is exercised end to end for each scraper, exactly as it would run
against a real site, without needing real network access or Chromium
binaries in this sandbox.
"""
import pytest

import scrapers.estimate_common as estimate_common
from scrapers.zillow_scraper import get_zillow_estimate
from scrapers.realtor_scraper import get_realtor_estimate
from scrapers.redfin_scraper import get_redfin_estimate
from scrapers.market_conditions import get_market_conditions


@pytest.fixture(autouse=True)
def _no_rate_limit_delay(monkeypatch):
    """
    estimate_common enforces a real MIN_DELAY_SECONDS politeness delay
    between outbound requests (shared across all four scraper modules) -
    correct behavior in production, but it would make ~20 sequential
    mocked-Playwright test calls take almost a minute for no reason here.
    Zero it out for the duration of each test in this module only.
    """
    monkeypatch.setattr(estimate_common, "MIN_DELAY_SECONDS", 0)


class _FakePage:
    def __init__(self, text=None, raise_on_goto=None):
        self._text = text
        self._raise_on_goto = raise_on_goto

    def set_default_timeout(self, ms):
        pass

    def goto(self, url, wait_until=None, timeout=None):
        if self._raise_on_goto:
            raise self._raise_on_goto

    def inner_text(self, selector):
        return self._text


class _FakeBrowser:
    def __init__(self, page):
        self._page = page
        self.closed = False

    def new_page(self, user_agent=None):
        return self._page

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, browser):
        self._browser = browser

    def launch(self, headless=True):
        return self._browser


class _FakePlaywrightContext:
    def __init__(self, browser):
        self.chromium = _FakeChromium(browser)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


def _patch_playwright(monkeypatch, text=None, raise_on_goto=None):
    """Patch playwright.sync_api.sync_playwright so estimate_common's
    `from playwright.sync_api import sync_playwright` (executed fresh
    inside fetch_page_text on every call) picks up the fake. Returns the
    fake browser so tests can assert on e.g. whether it was ever launched."""
    page = _FakePage(text=text, raise_on_goto=raise_on_goto)
    browser = _FakeBrowser(page)

    def _fake_sync_playwright():
        return _FakePlaywrightContext(browser)

    monkeypatch.setattr("playwright.sync_api.sync_playwright", _fake_sync_playwright)
    return browser


# --- Zillow ---

def test_zillow_success(monkeypatch):
    _patch_playwright(monkeypatch, text="123 Main St\nZestimate® $412,300\n")
    assert get_zillow_estimate("123 Main St, Tampa, FL 33602") == 412300.0


def test_zillow_no_estimate_found(monkeypatch):
    _patch_playwright(monkeypatch, text="123 Main St - no listing found")
    assert get_zillow_estimate("123 Main St, Tampa, FL 33602") is None


def test_zillow_blocked_page(monkeypatch):
    _patch_playwright(monkeypatch, text="Please complete the CAPTCHA to continue")
    assert get_zillow_estimate("123 Main St, Tampa, FL 33602") is None


def test_zillow_navigation_failure(monkeypatch):
    _patch_playwright(monkeypatch, raise_on_goto=TimeoutError("navigation timeout"))
    assert get_zillow_estimate("123 Main St, Tampa, FL 33602") is None


def test_zillow_empty_address_never_launches_browser(monkeypatch):
    browser = _patch_playwright(monkeypatch, text="Zestimate® $412,300")
    assert get_zillow_estimate("") is None
    assert get_zillow_estimate("   ") is None
    assert browser.closed is False  # launch() was never reached


# --- Realtor.com ---

def test_realtor_success(monkeypatch):
    _patch_playwright(monkeypatch, text="Realtor.com Estimate $305,000")
    assert get_realtor_estimate("456 Oak Ave, Tampa, FL 33602") == 305000.0


def test_realtor_no_estimate_found(monkeypatch):
    _patch_playwright(monkeypatch, text="No matching properties")
    assert get_realtor_estimate("456 Oak Ave, Tampa, FL 33602") is None


def test_realtor_blocked_page(monkeypatch):
    _patch_playwright(monkeypatch, text="Unusual traffic detected from your network")
    assert get_realtor_estimate("456 Oak Ave, Tampa, FL 33602") is None


def test_realtor_navigation_failure(monkeypatch):
    _patch_playwright(monkeypatch, raise_on_goto=RuntimeError("net::ERR_CONNECTION_RESET"))
    assert get_realtor_estimate("456 Oak Ave, Tampa, FL 33602") is None


# --- Redfin ---

def test_redfin_success(monkeypatch):
    _patch_playwright(monkeypatch, text="Redfin Estimate $389,450")
    assert get_redfin_estimate("789 Pine Rd, Tampa, FL 33602") == 389450.0


def test_redfin_no_estimate_found(monkeypatch):
    _patch_playwright(monkeypatch, text="No homes match your search")
    assert get_redfin_estimate("789 Pine Rd, Tampa, FL 33602") is None


def test_redfin_blocked_page(monkeypatch):
    _patch_playwright(monkeypatch, text="Are you a robot? Verify to proceed.")
    assert get_redfin_estimate("789 Pine Rd, Tampa, FL 33602") is None


def test_redfin_navigation_failure(monkeypatch):
    _patch_playwright(monkeypatch, raise_on_goto=RuntimeError("net::ERR_CONNECTION_RESET"))
    assert get_redfin_estimate("789 Pine Rd, Tampa, FL 33602") is None


# --- Market conditions ---

def test_market_conditions_seller_market(monkeypatch):
    _patch_playwright(monkeypatch, text="Market Overview: This is a Seller's Market.")
    assert get_market_conditions("Hillsborough", "33602") == "seller_market"


def test_market_conditions_buyer_market(monkeypatch):
    _patch_playwright(monkeypatch, text="Market Overview: This is a Buyer's Market.")
    assert get_market_conditions("Hillsborough", "33602") == "buyer_market"


def test_market_conditions_unrecognized_page(monkeypatch):
    _patch_playwright(monkeypatch, text="Market Overview: figures are mixed this quarter.")
    assert get_market_conditions("Hillsborough", "33602") is None


def test_market_conditions_blocked_page(monkeypatch):
    _patch_playwright(monkeypatch, text="Access to this page has been denied")
    assert get_market_conditions("Hillsborough", "33602") is None


def test_market_conditions_navigation_failure(monkeypatch):
    _patch_playwright(monkeypatch, raise_on_goto=TimeoutError("navigation timeout"))
    assert get_market_conditions("Hillsborough", "33602") is None


def test_market_conditions_no_zip_never_launches_browser(monkeypatch):
    browser = _patch_playwright(monkeypatch, text="This is a Seller's Market.")
    assert get_market_conditions("Hillsborough", "") is None
    assert get_market_conditions("Hillsborough", None) is None
    assert browser.closed is False
