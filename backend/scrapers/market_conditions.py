"""
market_conditions.py - on-demand "buyer's market" / "seller's market"
classification, plus zip-level median sale price (Phase B.2, 2026-07-13),
for a county/zip. Called by GET /api/properties/{id}/enrich (Phase 1 spec).

Redfin publishes a plain-language market classification sentence (e.g.
"This is a Seller's Market.") AND a "Median Sale Price" figure on the same
per-zip-code housing market overview page, which is the only free,
non-paid-API source identified for either signal (unlike absorption_rate/
crime_rate in scoring.py, which remain honest placeholders pending a real
data source per PROJECT_CONTEXT.md). Both are extracted from a single page
fetch (get_market_conditions_and_median_price) rather than two separate
requests, since they live on the same URL - halves the load on Redfin
versus fetching it twice.

Same honesty rules as scrapers/estimate_common.py: real best-effort
Playwright attempt, returns None for whichever signal(s) can't be found
(never a guessed classification or price) if the zip is missing, the page
can't be loaded/is blocked, or the text isn't found on the page. NOT
live-verified against redfin.com from this sandbox (this session confirmed
redfin.com is unreachable from this dev environment's network egress,
same restriction noted throughout PROJECT_CONTEXT.md) - verify live once
deployed.
"""
import logging
import re
from typing import Dict, Optional

from scrapers.estimate_common import extract_dollar_amount_near_label, fetch_page_text

logger = logging.getLogger("scrapers.market_conditions")

MARKET_URL_TEMPLATE = "https://www.redfin.com/zipcode/{zip_code}/housing-market"

SELLER_MARKET_PHRASES = ("seller's market", "sellers market")
BUYER_MARKET_PHRASES = ("buyer's market", "buyers market")
MEDIAN_PRICE_LABELS = ("Median Sale Price",)


def get_market_conditions_and_median_price(zip_code: str) -> Dict[str, Optional[object]]:
    """
    Returns {"market_conditions": "buyer_market"|"seller_market"|None,
              "zip_median_sale_price": float|None,
              "source_url": str|None}
    from a single fetch of Redfin's per-zip housing-market page. Either
    (or both) result fields can be None independently if that specific
    signal isn't found on the page, even when the fetch itself succeeds.
    """
    if not zip_code or not zip_code.strip():
        logger.info("No zip_code provided; cannot look up market conditions/median price.")
        return {"market_conditions": None, "zip_median_sale_price": None, "source_url": None}

    url = MARKET_URL_TEMPLATE.format(zip_code=zip_code.strip())
    text = fetch_page_text(url)
    if not text:
        return {"market_conditions": None, "zip_median_sale_price": None, "source_url": url}

    result: Dict[str, Optional[object]] = {
        "market_conditions": None,
        "zip_median_sale_price": None,
        "source_url": url,
    }

    lowered = text.lower()
    if any(phrase in lowered for phrase in SELLER_MARKET_PHRASES):
        result["market_conditions"] = "seller_market"
    elif any(phrase in lowered for phrase in BUYER_MARKET_PHRASES):
        result["market_conditions"] = "buyer_market"
    else:
        logger.info("No buyer's/seller's market phrase found for zip %r at %s", zip_code, url)

    median_price = extract_dollar_amount_near_label(text, MEDIAN_PRICE_LABELS)
    if median_price is not None:
        result["zip_median_sale_price"] = median_price
    else:
        logger.info("No Median Sale Price figure found for zip %r at %s", zip_code, url)

    return result


def get_market_conditions(county: str, zip_code: str) -> Optional[str]:
    """
    Backward-compatible wrapper kept for existing callers/tests: returns
    just the market-conditions classification. `county` is accepted per
    the original Phase 1 spec's signature and included in log messages
    only - the actual lookup is keyed off zip_code since that's what
    Redfin's market-overview URL requires.
    """
    result = get_market_conditions_and_median_price(zip_code)
    if county and not zip_code:
        logger.info("No zip_code provided for county %r; cannot look up market conditions.", county)
    return result["market_conditions"]
