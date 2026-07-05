"""
estimate_common.py - shared helpers for the on-demand third-party value
estimate scrapers used by GET /api/properties/{id}/enrich:
zillow_scraper.py, realtor_scraper.py, redfin_scraper.py, and
market_conditions.py.

Same honesty rules as the auction-listing scrapers in this package
(see scrapers/base.py, scrapers/realauction_playwright.py):

- Never fabricate a number. If a page can't be loaded, is blocked
  (CAPTCHA / bot-detection interstitial), or doesn't contain a recognizable
  estimate figure, the calling scraper returns None rather than guessing.
- Zillow, Realtor.com, and Redfin are commercial, heavily bot-protected
  sites (publicly documented anti-automation measures on at least Zillow
  and Redfin). A plain headless Playwright session with no residential
  proxy or CAPTCHA-solving service is likely to be challenged or blocked in
  production. Exactly like realauction_playwright.py, this has NOT been
  live-verified against the real sites from this dev sandbox (no network
  egress here) - the extraction logic is written from each site's publicly
  known page copy (Zillow: "Zestimate"; Redfin: "Redfin Estimate";
  Realtor.com: "Realtor.com Estimate") with a resilient regex-based
  fallback so small DOM/class-name changes don't silently break it. Live
  smoke-testing is required once this runs somewhere with real network
  access (see PROJECT_CONTEXT.md).
- Rate limited politely: a single shared monotonic-clock delay
  (MIN_DELAY_SECONDS) is enforced across all callers of fetch_page_text,
  and every page load is capped at a 30s timeout per the Phase 1 spec.

REAL VERIFICATION LOG (2026-07-05, live production `/enrich` test, see
PROJECT_CONTEXT.md): calling this against the real Zillow and Redfin sites
consistently hit `Page.goto: Timeout 30000ms exceeded` waiting for
`wait_until="networkidle"` - no CAPTCHA/block text was ever detected
because the page never finished loading in the first place. Both sites
carry on continuous background traffic (analytics beacons, live-price
polling, etc.) that apparently never lets the network go fully idle for
Playwright's networkidle heuristic. Fixed by switching to
`wait_until="domcontentloaded"` (fires once the DOM itself is parsed,
regardless of ongoing background XHR/fetch polling) followed by an
explicit short settle wait, which is the standard fix for this exact class
of "page never goes idle" issue.
- Idempotent: fetch_page_text has no side effects beyond the outbound
  request itself, so calling any of the get_*_estimate() functions
  repeatedly for the same address is always safe.
"""
import re
import time
import logging
from typing import Optional, Sequence
from urllib.parse import quote

logger = logging.getLogger("scrapers.estimates")

TIMEOUT_MS = 30_000  # 30 seconds per scraper, per the Phase 1 spec
MIN_DELAY_SECONDS = 3.0

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_last_request_time: Optional[float] = None


def _respect_rate_limit():
    """Shared across zillow/realtor/redfin/market_conditions so a burst of
    enrich calls doesn't hammer any one of these sites back-to-back."""
    global _last_request_time
    if _last_request_time is not None:
        elapsed = time.monotonic() - _last_request_time
        wait_for = MIN_DELAY_SECONDS - elapsed
        if wait_for > 0:
            time.sleep(wait_for)
    _last_request_time = time.monotonic()


def _looks_blocked(text: Optional[str]) -> bool:
    """Heuristic check for a bot-block/CAPTCHA interstitial rather than a
    real page. Errs toward treating ambiguous pages as blocked (returns
    None upstream) rather than risking a fabricated/garbage figure."""
    if not text or not text.strip():
        return True
    lowered = text.lower()
    block_markers = (
        "captcha",
        "are you a robot",
        "access to this page has been denied",
        "unusual traffic",
        "press and hold",
        "verify you are a human",
    )
    return any(marker in lowered for marker in block_markers)


def fetch_page_text(url: str) -> Optional[str]:
    """
    Launch a headless Chromium page via Playwright, navigate to `url`, and
    return the rendered page's visible text content.

    Returns None (never raises) on any failure: playwright not installed,
    navigation timeout (capped at TIMEOUT_MS), network error, or an
    apparent bot-block/CAPTCHA interstitial.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning(
            "playwright not installed / browser binaries not provisioned "
            "(`pip install playwright && playwright install --with-deps "
            "chromium`). Cannot fetch %s.",
            url,
        )
        return None

    _respect_rate_limit()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=USER_AGENT)
                page.set_default_timeout(TIMEOUT_MS)
                page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
                # domcontentloaded fires as soon as the DOM is parsed, before
                # client-side JS has necessarily finished rendering dynamic
                # content (e.g. a Zestimate figure injected after initial
                # paint). A short settle wait gives that JS a chance to run
                # without risking the same indefinite hang networkidle could
                # cause on pages with continuous background polling.
                try:
                    page.wait_for_timeout(3000)
                except Exception:
                    pass
                text = page.inner_text("body")
            finally:
                browser.close()
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None

    if _looks_blocked(text):
        logger.warning(
            "Response from %s looks like a bot-block/CAPTCHA page rather "
            "than real content; discarding rather than risking a garbage "
            "parse.",
            url,
        )
        return None

    return text


DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/?q={query}"


def resolve_property_url_via_search(
    address: str, domain: str, path_prefix: str, url_pattern: str
) -> Optional[str]:
    """
    Resolve `address` to a specific listing-site detail-page URL by querying
    DuckDuckGo's no-JS HTML search endpoint for
    `site:<domain><path_prefix> <address>` and pulling the first matching
    URL out of the plain-text results.

    REAL VERIFICATION LOG (2026-07-05): both Zillow and Realtor.com require
    an opaque internal ID in the URL path (Zillow: zpid; Realtor.com:
    an "M<mls-market-id>-<listing-id>" suffix) that cannot be guessed from
    the address alone - confirmed live that constructing a URL from just
    the address slug (e.g. zillow.com/homes/<address>_rb/ or
    zillow.com/homedetails/<address>/ with no zpid) does NOT reach the
    property page; Zillow silently redirects to a generic rental search
    instead. Their own in-page address search also requires a live
    autocomplete GraphQL call with an internal query the frontend doesn't
    expose simply. DuckDuckGo's html.duckduckgo.com/html/ endpoint (JS-free,
    meant for this kind of use) reliably surfaces the real canonical
    detail-page URL - including the zpid/listing-id - as its top hit for an
    exact-address query; confirmed live for
    "17915 Saint Croix Isle Dr, Tampa, FL 33647" on both sites.

    Returns None if no matching URL is found in the search results or the
    search request itself fails (never fabricates a listing URL/ID).
    """
    if not address or not address.strip():
        return None

    query = f"site:{domain}{path_prefix} {address.strip()}"
    search_url = DUCKDUCKGO_HTML_URL.format(query=quote(query))
    text = fetch_page_text(search_url)
    if not text:
        return None

    match = re.search(url_pattern, text)
    if not match:
        return None
    return "https://" + match.group(0)


def fetch_raw_response_text(url: str) -> Optional[str]:
    """
    Like fetch_page_text, but for endpoints that return raw JSON/text rather
    than an HTML page to render (e.g. Redfin's location-autocomplete API).
    Uses page.content()'s <pre> body that Chromium renders for a raw JSON
    response, falling back to inner_text, so callers get the literal
    response body to parse themselves. Returns None on any failure - same
    never-fabricate contract as fetch_page_text.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning(
            "playwright not installed / browser binaries not provisioned. "
            "Cannot fetch %s.",
            url,
        )
        return None

    _respect_rate_limit()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=USER_AGENT)
                page.set_default_timeout(TIMEOUT_MS)
                page.goto(url, timeout=TIMEOUT_MS)
                text = page.inner_text("body")
            finally:
                browser.close()
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None

    return text


def extract_dollar_amount_near_label(text: str, labels: Sequence[str]) -> Optional[float]:
    """
    Search rendered page text for the first occurrence of any of `labels`
    (case-insensitive) followed by a dollar figure, e.g.
    'Zestimate® $412,300' or 'Redfin Estimate: $389,000'.

    REAL VERIFICATION LOG (2026-07-05): live-checked Realtor.com's actual
    rendered detail page for a real address and found the "RealEstimate"
    label and its dollar figure are separated by ~90 characters of
    interleaved chart/table UI text ("Chart Table July 2026 Valuation
    provider Estimate Collateral Analytics") once the page is flattened to
    plain text - the original ~40-char window was too tight and would have
    missed a real, present estimate. Widened to 400 chars to tolerate this
    kind of layout noise while still requiring the figure look like a real
    dollar amount (>= $1,000) rather than matching some unrelated stray
    number far down the page.

    Returns None if no label/figure pair is found or the figure looks like
    a stray small number (e.g. a bed/bath count) rather than a real
    estimate - never fabricates a fallback number.
    """
    if not text:
        return None
    for label in labels:
        pattern = re.compile(
            re.escape(label) + r"[^$]{0,400}\$\s?([\d,]{4,})",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            continue
        cleaned = match.group(1).replace(",", "")
        try:
            value = float(cleaned)
        except ValueError:
            continue
        if value >= 1_000:  # sanity floor - a real home value estimate
            return value
    return None
