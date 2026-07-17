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

# 2026-07-17: every fetch failure up to now has been swallowed as a
# logger.warning() that never surfaces anywhere in the API response - so
# from production, a "bot block", a Chromium launch failure, a plain
# network timeout, and DNS failure are all indistinguishable (they all just
# show up as a null estimate with an empty enrich_errors list). That's not
# good enough to actually diagnose what's failing. This module-level slot
# records the real exception (type + message) from the most recent failed
# fetch so callers (zillow_scraper.py etc., and ultimately main.py's
# enrich_property) can surface the *actual* reason in enrich_errors instead
# of a generic "unavailable". Never used to change behavior (still never
# fabricates a number/URL) - purely diagnostic.
_last_fetch_diagnostic: Optional[str] = None


def get_last_fetch_diagnostic() -> Optional[str]:
    """Real reason the most recent fetch_page_text/fetch_raw_response_text
    call returned None, if any - see _last_fetch_diagnostic above."""
    return _last_fetch_diagnostic


def _record_diagnostic(url: str, detail: str) -> None:
    global _last_fetch_diagnostic
    _last_fetch_diagnostic = f"{url}: {detail}"
    logger.warning("Fetch diagnostic for %s: %s", url, detail)


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
        _record_diagnostic(url, "playwright not installed / browser binaries not provisioned")
        return None

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as launch_exc:
                # Distinguished from a navigation/network failure below -
                # if Chromium itself can't start (common Docker failure
                # mode: sandbox permissions, /dev/shm too small), every
                # single fetch would fail identically regardless of which
                # site it's aimed at. Tagged explicitly so this is
                # distinguishable from a genuine per-site block.
                _record_diagnostic(url, f"BROWSER LAUNCH FAILED: {type(launch_exc).__name__}: {launch_exc}")
                return None
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
        _record_diagnostic(url, f"{type(exc).__name__}: {exc}")
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
            _record_diagnostic(
                url,
                f"BOT-BLOCK TEXT DETECTED in response (len={len(text)}): "
                f"{text[:200]!r}",
            )
            return None

        if attempt < RETRY_ATTEMPTS:
            logger.info(
                "fetch_page_text: attempt %d/%d for %s returned nothing "
                "usable; retrying in %.0fs.",
                attempt, RETRY_ATTEMPTS, url, RETRY_BACKOFF_SECONDS,
            )
            time.sleep(RETRY_BACKOFF_SECONDS)

    if last_text == "":
        # 2026-07-17 bugfix: only overwrite the diagnostic with this generic
        # message when the last attempt genuinely returned empty text with
        # no exception (last_text == "", not None). If last_text is None,
        # _fetch_page_text_once already recorded the real exception/launch-
        # failure reason inside itself - overwriting it here would discard
        # the one piece of information that explains what's actually wrong.
        _record_diagnostic(url, f"EMPTY RESPONSE after {RETRY_ATTEMPTS} attempts (no exception, no block text - page loaded but body text was blank)")
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

    2026-07-16 UPDATE: a user reported that none of the branded links ever
    reach the actual property - live-testing this function's search results
    in a real Chrome session (query: "site:zillow.com 17915 Saint Croix Isle
    Dr Tampa FL 33647") showed DuckDuckGo is reachable and returns real
    results, but the FIRST regex match in the page text is not necessarily
    the right listing - nearby/similar addresses ("17912 Saint Croix Isle
    Dr", "17915 Saint Croix Dr" with a different zip and no "Isle") also
    matched the URL pattern and could easily have been picked instead of the
    exact address requested. Grabbing "the first match" was a real accuracy
    bug: it could silently link to a nearby but WRONG property. Fixed by
    scanning every candidate match and only accepting one whose surrounding
    result text actually contains the input address's house number - if no
    candidate's context contains that house number, this now returns None
    (never guesses a nearby address) rather than silently picking a
    plausible-looking but wrong listing.
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

    house_number_match = re.match(r"\s*(\d+)", address.strip())
    house_number = house_number_match.group(1) if house_number_match else None

    candidates = list(re.finditer(url_pattern, text))
    if not candidates:
        return None

    if not house_number:
        # No leading house number to verify against (unusual address
        # format) - fall back to the previous "first match" behavior rather
        # than refusing outright.
        return "https://" + candidates[0].group(0)

    for m in candidates:
        # DuckDuckGo's html results place each result's title/snippet text
        # right around its URL, and that snippet virtually always repeats
        # the property's street address - checking a window of text
        # immediately preceding the URL match for the exact house number is
        # a cheap, effective way to confirm this candidate is for the right
        # property rather than a same-street or same-number-elsewhere
        # neighbor.
        window = text[max(0, m.start() - 300):m.end()]
        if re.search(rf"\b{re.escape(house_number)}\b", window):
            return "https://" + m.group(0)

    logger.info(
        "resolve_property_url_via_search: found %d candidate URL(s) on %s "
        "for %r but none had house number %r in their nearby result text - "
        "refusing to guess a nearby-but-possibly-wrong listing.",
        len(candidates), domain, address, house_number,
    )
    return None


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
        _record_diagnostic(url, "playwright not installed / browser binaries not provisioned")
        return None

    status_seen = None
    last_attempt_raised = False
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        _respect_rate_limit()
        last_attempt_raised = False
        try:
            with sync_playwright() as p:
                request_context = p.request.new_context(
                    user_agent=USER_AGENT, timeout=TIMEOUT_MS
                )
                try:
                    response = request_context.get(url, timeout=TIMEOUT_MS)
                    status_seen = response.status
                    text = response.text()
                finally:
                    request_context.dispose()
        except Exception as exc:
            # 2026-07-17 bugfix: this used to get silently overwritten by
            # the generic "no exception" diagnostic below once the retry
            # loop finished, even when every single attempt actually raised
            # a real exception here - meaning the one piece of information
            # that would explain the failure (a real Python exception
            # message) was being discarded right before it reached anyone.
            # last_attempt_raised prevents that overwrite.
            _record_diagnostic(url, f"{type(exc).__name__}: {exc} (attempt {attempt}/{RETRY_ATTEMPTS})")
            text = None
            last_attempt_raised = True

        if text and text.strip():
            return text

        if attempt < RETRY_ATTEMPTS:
            logger.info(
                "fetch_raw_response_text: attempt %d/%d for %s returned "
                "nothing; retrying in %.0fs.",
                attempt, RETRY_ATTEMPTS, url, RETRY_BACKOFF_SECONDS,
            )
            time.sleep(RETRY_BACKOFF_SECONDS)

    if not last_attempt_raised:
        _record_diagnostic(
            url,
            f"EMPTY/NO RESPONSE after {RETRY_ATTEMPTS} attempts "
            f"(last HTTP status seen: {status_seen!r}, no exception on last attempt - "
            f"request succeeded but body was empty)",
        )
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
