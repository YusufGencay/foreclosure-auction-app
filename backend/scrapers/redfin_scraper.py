"""
redfin_scraper.py - on-demand Redfin Estimate lookup for a single property
address. Called by GET /api/properties/{id}/enrich (Phase 1 spec).

See scrapers/estimate_common.py for the shared honesty/rate-limit/timeout
rules this module follows. Real best-effort attempt via Playwright, returns
None (never a guessed number) on any failure, blocked page, or missing
figure. NOT live-verified against redfin.com from this sandbox (no network
egress) - see PROJECT_CONTEXT.md.
"""
import logging
from urllib.parse import quote

from scrapers.estimate_common import extract_dollar_amount_near_label, fetch_page_text

logger = logging.getLogger("scrapers.redfin")

# Redfin's general search endpoint; an exact street-address query typically
# resolves straight to the property detail page.
SEARCH_URL_TEMPLATE = "https://www.redfin.com/search?query={query}"

REDFIN_LABELS = ["Redfin Estimate"]


def get_redfin_estimate(address: str) -> float | None:
    """
    Look up Redfin's estimate for `address`. Returns the dollar figure as a
    float, or None if the property couldn't be found, the page was
    blocked, or no estimate is published for it (never fabricated).
    """
    if not address or not address.strip():
        return None

    url = SEARCH_URL_TEMPLATE.format(query=quote(address.strip()))
    text = fetch_page_text(url)
    if not text:
        return None

    estimate = extract_dollar_amount_near_label(text, REDFIN_LABELS)
    if estimate is None:
        logger.info("No Redfin Estimate found for address %r at %s", address, url)
    return estimate
