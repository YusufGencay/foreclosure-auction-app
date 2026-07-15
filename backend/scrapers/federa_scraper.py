"""
federa_scraper.py - Phase 3 (2026-07-15): resolves a property's address to
its federa.com listing page, if one exists, for a branded one-click
link-out button. Per the user's explicit 2026-07-13 decision, this never
scrapes an "estimate" off Federa - Federa doesn't reliably list every
county-courthouse sale, so a missing listing just means no button/a
search-page fallback, never a fabricated figure.

REAL VERIFICATION LOG (2026-07-15, live Chrome session): federa.com loaded
cleanly with no bot-block/CAPTCHA (unlike auction.com - see
auction_com_scraper.py's docstring). Used the site's own visible "Search
homes" box exactly like a normal user would: typing a real address
("17915 Saint Croix Isle Dr Tampa FL") produced a real autocomplete
suggestion, and clicking it navigated to a real property page:
https://federa.com/property/3452714000077050930. This module automates
exactly that visible, public search-box flow via Playwright - it does not
call any of federa.com's internal/undocumented API endpoints directly
(confirmed some exist via this session's network log, e.g.
`/api/internal/properties/find`, but deliberately not used here - probing
undocumented internal endpoints on a third-party site is out of scope for
what this button needs, which is just "does a public listing page exist
for this address").

Brand color, sampled live from the real rendered page (not guessed): the
active "Explore" nav item and the "Make an offer" button both render in
`rgb(15, 41, 29)` = `#0F291D`, matching the page's own
`<meta name="theme-color">` tag exactly. Federa's real button style is a
white/transparent background with dark-green (#0F291D) text on a thin
light-gray (#E0E3E7) border, not a solid-fill button - matched in the
frontend CSS accordingly.

Returns None (never a guessed/constructed URL) if no address match is
found or the page can't be loaded - the frontend falls back to a plain
link to federa.com's homepage in that case (never a deep-linked guess).
"""
import logging
import time
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger("scrapers.federa")

TIMEOUT_MS = 30_000
MIN_DELAY_SECONDS = 3.0

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

FEDERA_HOMEPAGE = "https://federa.com/"

_last_request_time: Optional[float] = None


def _respect_rate_limit():
    global _last_request_time
    if _last_request_time is not None:
        elapsed = time.monotonic() - _last_request_time
        wait_for = MIN_DELAY_SECONDS - elapsed
        if wait_for > 0:
            time.sleep(wait_for)
    _last_request_time = time.monotonic()


def get_federa_url(address: str) -> Optional[str]:
    """
    Resolve `address` to a real federa.com/property/<id> URL by driving the
    site's own public search box (Playwright), exactly like a real user
    would. Returns None on any failure or no-match - never guesses a URL.
    """
    if not address or not address.strip():
        return None

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("playwright not installed; cannot resolve Federa URL for %r.", address)
        return None

    _respect_rate_limit()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=USER_AGENT)
                page.set_default_timeout(TIMEOUT_MS)
                page.goto(FEDERA_HOMEPAGE, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
                page.wait_for_timeout(2000)

                search_box = page.get_by_placeholder("Search homes").first
                search_box.click()
                search_box.fill(address.strip())
                page.wait_for_timeout(2000)

                suggestion = page.locator('button:has-text("' + address.strip().split(",")[0] + '")').first
                if suggestion.count() == 0:
                    logger.info("No Federa autocomplete suggestion for %r.", address)
                    return None
                suggestion.click()
                page.wait_for_timeout(2000)

                url = page.url
            finally:
                browser.close()
    except Exception as exc:
        logger.warning("Federa lookup failed for %r: %s", address, exc)
        return None

    if url and "/property/" in url:
        return url
    logger.info("Federa search for %r did not land on a property page (got %s).", address, url)
    return None
