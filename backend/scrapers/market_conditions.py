"""
market_conditions.py - on-demand "buyer's market" / "seller's market"
classification for a county/zip. Called by GET /api/properties/{id}/enrich
(Phase 1 spec).

Redfin publishes a plain-language market classification sentence (e.g.
"This is a Seller's Market.") on its per-zip-code housing market overview
pages, which is the only free, non-paid-API source identified for this
signal (unlike absorption_rate/crime_rate in scoring.py, which remain
honest placeholders pending a real data source per PROJECT_CONTEXT.md).

Same honesty rules as scrapers/estimate_common.py: real best-effort
Playwright attempt, returns None (never a guessed classification) if the
zip is missing, the page can't be loaded/is blocked, or the sentence isn't
found on the page. NOT live-verified against redfin.com from this sandbox
(no network egress) - see PROJECT_CONTEXT.md.
"""
import logging
from typing import Optional

from scrapers.estimate_common import fetch_page_text

logger = logging.getLogger("scrapers.market_conditions")

MARKET_URL_TEMPLATE = "https://www.redfin.com/zipcode/{zip_code}/housing-market"

SELLER_MARKET_PHRASES = ("seller's market", "sellers market")
BUYER_MARKET_PHRASES = ("buyer's market", "buyers market")


def get_market_conditions(county: str, zip_code: str) -> Optional[str]:
    """
    Returns "buyer_market" or "seller_market" for the given zip code's
    housing market, or None if it can't be determined (never fabricated).
    `county` is accepted per the Phase 1 spec's signature and included in
    log messages, but the actual lookup below is keyed off zip_code since
    that's what Redfin's market-overview URL requires.
    """
    if not zip_code or not zip_code.strip():
        logger.info("No zip_code provided for county %r; cannot look up market conditions.", county)
        return None

    url = MARKET_URL_TEMPLATE.format(zip_code=zip_code.strip())
    text = fetch_page_text(url)
    if not text:
        return None

    lowered = text.lower()
    if any(phrase in lowered for phrase in SELLER_MARKET_PHRASES):
        return "seller_market"
    if any(phrase in lowered for phrase in BUYER_MARKET_PHRASES):
        return "buyer_market"

    logger.info(
        "No buyer's/seller's market phrase found for county %r zip %r at %s",
        county, zip_code, url,
    )
    return None
