"""
zillow_scraper.py - on-demand Zestimate lookup for a single property
address. Called by GET /api/properties/{id}/enrich (Phase 1 spec), never
as part of the county auction-listing scrapers.

See scrapers/estimate_common.py for the shared honesty/rate-limit/timeout
rules this module follows. Short version: real best-effort attempt via
Playwright, returns None (never a guessed number) on any failure, blocked
page, or missing figure. NOT live-verified against zillow.com from this
sandbox (no network egress) - see PROJECT_CONTEXT.md.
"""
import logging
from urllib.parse import quote

from scrapers.estimate_common import extract_dollar_amount_near_label, fetch_page_text

logger = logging.getLogger("scrapers.zillow")

# Zillow's keyword/address search URL. An exact-match address typically
# redirects straight to the property detail page, which is where the
# Zestimate figure lives.
SEARCH_URL_TEMPLATE = "https://www.zillow.com/homes/{query}_rb/"

ZILLOW_LABELS = ["Zestimate®", "Zestimate"]


def get_zillow_estimate(address: str) -> float | None:
    """
    Look up Zillow's Zestimate for `address`. Returns the dollar figure as
    a float, or None if the property couldn't be found, the page was
    blocked, or no Zestimate is published for it (never fabricated).
    """
    if not address or not address.strip():
        return None

    url = SEARCH_URL_TEMPLATE.format(query=quote(address.strip()))
    text = fetch_page_text(url)
    if not text:
        return None

    estimate = extract_dollar_amount_near_label(text, ZILLOW_LABELS)
    if estimate is None:
        logger.info("No Zestimate figure found for address %r at %s", address, url)
    return estimate
