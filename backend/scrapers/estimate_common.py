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

# Phase 2b (2026-07-15) resolver hardening: a live production test against
# a real property (see PROJECT_CONTEXT.md, 2026-07-15 session) showed
# fetch_page_text/fetch_raw_response_text returning None with no exception
# and no explicit CAPTCHA text detected by _looks_blocked - consistent with
# a transient network/navigation failure (or a brief soft-block) rather
# than a permanent one. One retry with a short backoff costs little and
# recovers from purely transient failures; it deliberately does NOT retry
# when _looks_blocked already matched real block text, since hammering a
# page that's actively showing a CAPTCHA is neither polite nor likely to
# succeed on the very next attempt.
RETRY_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 4.0

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


def _fetch_page_text_once(url: str) -> Optional[str]:
    """Single attempt - see fetch_page_text for the retry wrapper around this."""
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

    return text


def fetch_page_text(url: str) -> Optional[str]:
    """
    Launch a headless Chromium page via Playwright, navigate to `url`, and
    return the rendered page's visible text content.

    Returns None (never raises) on any failure: playwright not installed,
    navigation timeout (capped at TIMEOUT_MS), network error, or an
    apparent bot-block/CAPTCHA interstitial.

    Phase 2b (2026-07-15): retries once (RETRY_ATTEMPTS) with a short
    backoff on a transient failure (exception, empty response) - but NOT
    when the response came back and _looks_blocked positively matched real
    CAPTCHA/block text, since that's a confirmed block rather than a blip
    and retrying immediately just spends more request budget for no
    expected benefit.
    """
    last_text = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        _respect_rate_limit()
        text = _fetch_page_text_once(url)
        last_text = text

        if text and not _looks_blocked(text):
            return text

        if text and _looks_blocked(text):
            logger.warning(
                "Response from %s looks like a bot-block/CAPTCHA page "
                "rather than real content; discarding rather than risking "
                "a garbage parse (not retrying - block looks confirmed).",
                url,
            )
            return None

        if attempt < RETRY_ATTEMPTS:
            logger.info(
                "fetch_page_text: attempt %d/%d for %s returned nothing "
                "usable; retrying in %.0fs.",
                attempt, RETRY_ATTEMPTS, url, RETRY_BACKOFF_SECONDS,
            )
            time.sleep(RETRY_BACKOFF_SECONDS)

    if last_text is None:
        logger.warning("fetch_page_text: no usable response from %s after %d attempt(s).", url, RETRY_ATTEMPTS)
    return None


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
    # DuckDuckGo's html.duckduckgo.com endpoint is plain server-rendered
    # HTML with no client-side JS needed to see the result links/snippets,
    # so it's fetched via the same raw-request path as the JSON APIs
    # (fetch_raw_response_text) rather than a full page render
    # (fetch_page_text) - faster, and avoids the exact class of
    # render/read race documented in fetch_raw_response_text's docstring.
    text = fetch_raw_response_text(search_url)
    if _looks_blocked(text):
        return None

    match = re.search(url_pattern, text)
    if not match:
        return None
    return "https://" + match.group(0)


def fetch_raw_response_text(url: str) -> Optional[str]:
    """
    Like fetch_page_text, but for endpoints that return raw JSON/text rather
    than an HTML page to render (e.g. Redfin's location-autocomplete API,
    DuckDuckGo's no-JS HTML search results).

    REAL VERIFICATION LOG (2026-07-05, live production `/enrich` test): the
    original version of this function did `page.goto(url)` then
    `page.inner_text("body")`, exactly like fetch_page_text - but for a raw
    JSON API response, Chromium renders its own JSON-viewer UI over the
    response rather than a plain text node, and reading that back via
    inner_text raced with the viewer's rendering in production: confirmed
    live via a real browser session that the raw response for a Redfin
    autocomplete call was the expected literal text
    ('{}&&{"version":648,...}'), but the SAME call through Playwright in
    production logged `json.JSONDecodeError: Extra data: line 1 column 5
    (char 4)` when parsing it - i.e. the text Playwright actually read back
    didn't match what a real interactive browser showed for the identical
    URL. Fixed by using Playwright's dedicated API request context
    (`playwright.request`) instead, which performs a plain HTTP GET and
    returns the exact response bytes with no DOM/rendering step at all -
    the correct tool for fetching a raw API/JSON endpoint rather than
    routing it through a page render. This is also faster (no browser page
    navigation) and carries fewer bot-detection signals than a full page
    load. Returns None on any failure - same never-fabricate contract as
    fetch_page_text.

    Phase 2b (2026-07-15): retries once (RETRY_ATTEMPTS) with a short
    backoff on an empty/failed response, mirroring fetch_page_text's retry
    behavior - a live production test showed this returning nothing for
    Redfin's autocomplete endpoint with no exception raised, consistent
    with a transient failure worth one retry.
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

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        _respect_rate_limit()
        try:
            with sync_playwright() as p:
                request_context = p.request.new_context(
                    user_agent=USER_AGENT, timeout=TIMEOUT_MS
                )
                try:
                    response = request_context.get(url, timeout=TIMEOUT_MS)
                    text = response.text()
                finally:
                    request_context.dispose()
        except Exception as exc:
            logger.warning("Failed to fetch %s (attempt %d/%d): %s", url, attempt, RETRY_ATTEMPTS, exc)
            text = None

        if text and text.strip():
            return text

        if attempt < RETRY_ATTEMPTS:
            logger.info(
                "fetch_raw_response_text: attempt %d/%d for %s returned "
                "nothing; retrying in %.0fs.",
                attempt, RETRY_ATTEMPTS, url, RETRY_BACKOFF_SECONDS,
            )
            time.sleep(RETRY_BACKOFF_SECONDS)

    logger.warning("fetch_raw_response_text: no usable response from %s after %d attempt(s).", url, RETRY_ATTEMPTS)
    return None


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
