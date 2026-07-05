"""
realtor_scraper.py - on-demand Realtor.com "RealEstimate" lookup for a
single property address. Called by GET /api/properties/{id}/enrich
(Phase 1 spec).

See scrapers/estimate_common.py for the shared honesty/rate-limit/timeout
rules this module follows.

REAL VERIFICATION LOG (2026-07-05): the previous version of this module
guessed a Realtor.com URL directly from the address
(`/realestateandhomes-search/<address>`), which is a search-results URL,
not a detail page - it would never surface a RealEstimate figure. Fixed by
resolving the address to its real
`realtor.com/realestateandhomes-detail/<slug>_M<market>-<listing-id>` URL
via estimate_common.resolve_property_url_via_search first. Live-checked the
resolved detail page for "17915 Saint Croix Isle Dr, Tampa, FL 33647" and
confirmed the page contains the literal "RealEstimate" label with a real
dollar figure (Collateral Analytics valuation) - but separated by ~90
characters of interleaved chart/table text once flattened to plain text,
which is why extract_dollar_amount_near_label's search window was widened
(see that function's docstring in estimate_common.py).
"""
import logging

from scrapers.estimate_common import (
    extract_dollar_amount_near_label,
    fetch_page_text,
    resolve_property_url_via_search,
)

logger = logging.getLogger("scrapers.realtor")

REALTOR_DOMAIN = "realtor.com"
REALTOR_PATH_PREFIX = "/realestateandhomes-detail"
REALTOR_URL_PATTERN = r"www\.realtor\.com/realestateandhomes-detail/[\w\-]+"

# Realtor.com has branded its automated valuation as "RealEstimate"
# (confirmed live 2026-07-05); "Realtor.com Estimate" kept as a secondary
# fallback label in case of page-copy variants.
REALTOR_LABELS = ["RealEstimate", "Realtor.com Estimate"]


def get_realtor_estimate(address: str) -> float | None:
    """
    Look up Realtor.com's estimate for `address`. Returns the dollar figure
    as a float, or None if the property couldn't be found, the page was
    blocked, or no estimate is published for it (never fabricated).
    """
    if not address or not address.strip():
        return None

    property_url = resolve_property_url_via_search(
        address, REALTOR_DOMAIN, REALTOR_PATH_PREFIX, REALTOR_URL_PATTERN
    )
    if not property_url:
        logger.info("No Realtor.com listing URL resolved for address %r", address)
        return None

    text = fetch_page_text(property_url)
    if not text:
        return None

    estimate = extract_dollar_amount_near_label(text, REALTOR_LABELS)
    if estimate is None:
        logger.info("No Realtor.com estimate found for address %r at %s", address, property_url)
    return estimate
