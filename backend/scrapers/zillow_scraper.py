"""
zillow_scraper.py - on-demand Zestimate lookup for a single property
address. Called by GET /api/properties/{id}/enrich (Phase 1 spec), never
as part of the county auction-listing scrapers.

See scrapers/estimate_common.py for the shared honesty/rate-limit/timeout
rules this module follows.

REAL VERIFICATION LOG (2026-07-05): the previous version of this module
guessed a Zillow URL directly from the address (`/homes/<address>_rb/`).
Live-checked via a real Chrome browser and confirmed that's wrong - Zillow
requires an internal `zpid` in the URL to reach a specific property's page;
without it, both `/homes/<address>_rb/` and `/homedetails/<address>/`
silently redirect to a generic rental search results page with zero
relation to the requested address. Fixed by resolving the address to its
real `zillow.com/homedetails/.../<zpid>_zpid/` URL via
estimate_common.resolve_property_url_via_search first (see that function's
docstring for why: Zillow's own address search requires a live internal
GraphQL call that isn't a simple guessable URL). Confirmed live for
"17915 Saint Croix Isle Dr, Tampa, FL 33647".
"""
import logging

from scrapers.estimate_common import (
    extract_dollar_amount_near_label,
    fetch_page_text,
    resolve_property_url_via_search,
)

logger = logging.getLogger("scrapers.zillow")

ZILLOW_DOMAIN = "zillow.com"
ZILLOW_PATH_PREFIX = "/homedetails"
ZILLOW_URL_PATTERN = r"www\.zillow\.com/homedetails/[\w\-]+/\d+_zpid/"

ZILLOW_LABELS = ["Zestimate®", "Zestimate"]


def get_zillow_estimate(address: str) -> float | None:
    """
    Look up Zillow's Zestimate for `address`. Returns the dollar figure as
    a float, or None if the property couldn't be found, the page was
    blocked, or no Zestimate is published for it (never fabricated).
    """
    if not address or not address.strip():
        return None

    property_url = resolve_property_url_via_search(
        address, ZILLOW_DOMAIN, ZILLOW_PATH_PREFIX, ZILLOW_URL_PATTERN
    )
    if not property_url:
        logger.info("No Zillow listing URL resolved for address %r", address)
        return None

    text = fetch_page_text(property_url)
    if not text:
        return None

    estimate = extract_dollar_amount_near_label(text, ZILLOW_LABELS)
    if estimate is None:
        logger.info("No Zestimate figure found for address %r at %s", address, property_url)
    return estimate
