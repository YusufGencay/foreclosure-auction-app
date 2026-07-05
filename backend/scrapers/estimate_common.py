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
- Idempotent: fetch_page_text has no side effects beyond the outbound
  request itself, so calling any of the get_*_estimate() functions
  repeatedly for the same address is always safe.
"""
import re
import time
import logging
from typing import Optional, Sequence

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
                page.goto(url, wait_until="networkidle", timeout=TIMEOUT_MS)
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


def extract_dollar_amount_near_label(text: str, labels: Sequence[str]) -> Optional[float]:
    """
    Search rendered page text for the first occurrence of any of `labels`
    (case-insensitive) followed within ~40 characters by a dollar figure,
    e.g. 'Zestimate® $412,300' or 'Redfin Estimate: $389,000'.

    Returns None if no label/figure pair is found or the figure looks like
    a stray small number (e.g. a bed/bath count) rather than a real
    estimate - never fabricates a fallback number.
    """
    if not text:
        return None
    for label in labels:
        pattern = re.compile(
            re.escape(label) + r"[^$0-9]{0,40}\$\s?([\d,]{4,})",
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
