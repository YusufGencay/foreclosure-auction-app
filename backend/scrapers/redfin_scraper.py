"""
redfin_scraper.py - on-demand Redfin Estimate lookup for a single property
address. Called by GET /api/properties/{id}/enrich (Phase 1 spec).

See scrapers/estimate_common.py for the shared honesty/rate-limit/timeout
rules this module follows.

REAL VERIFICATION LOG (2026-07-05): the previous version of this module used
`https://www.redfin.com/search?query=...`, which was WRONG - live-checked
via a real Chrome browser and confirmed that URL just redirects to the
Redfin homepage with no search results, meaning this scraper could never
have found real data. Confirmed the actual working flow, live, against
address "17915 Saint Croix Isle Dr, Tampa, FL 33647":

1. GET `https://www.redfin.com/stingray/do/location-autocomplete
   ?location=<address>&v=2` - Redfin's own address-autocomplete API.
   Returns a JSON body prefixed with the anti-JSON-hijacking guard `{}&&`
   (must be stripped before parsing), containing an `exactMatch` (or
   `payload.sections[].rows[]`) object with a `url` field, e.g.
   `/FL/Tampa/17915-Saint-Croix-Isle-Dr-33647/home/47184630`.
2. Navigate to `https://www.redfin.com` + that url. The rendered page
   contains the literal text "Redfin Estimate" followed by a dollar figure
   (confirmed live: "Redfin Estimate $812,676" for the address above).

Fixed to actually perform both steps rather than guessing a single search
URL. Still returns None (never a guessed number) on any failure, blocked
page, no address match, or missing estimate figure.
"""
import json
import logging
from urllib.parse import quote

from scrapers.estimate_common import (
    extract_dollar_amount_near_label,
    fetch_page_text,
    fetch_raw_response_text,
    resolve_property_url_via_search,
)

logger = logging.getLogger("scrapers.redfin")

AUTOCOMPLETE_URL_TEMPLATE = (
    "https://www.redfin.com/stingray/do/location-autocomplete"
    "?location={query}&v=2"
)

# Fallback if Redfin's own autocomplete API changes shape or starts
# blocking headless requests: Redfin detail URLs don't share one fixed
# path prefix (they're /<state>/<city>/<slug>/home/<id>), so this pattern
# just requires the distinctive "/home/<digits>" suffix common to all of
# them.
REDFIN_DOMAIN = "redfin.com"
REDFIN_PATH_PREFIX = ""
REDFIN_URL_PATTERN = r"www\.redfin\.com/[\w/\-]+/home/\d+"

REDFIN_LABELS = ["Redfin Estimate"]


def _resolve_property_url(address: str) -> str | None:
    """
    Resolve a free-text address to Redfin's internal property page path
    (e.g. "/FL/Tampa/17915-Saint-Croix-Isle-Dr-33647/home/47184630") via
    Redfin's own autocomplete API. Returns None if no address match is
    found or the API call fails.
    """
    url = AUTOCOMPLETE_URL_TEMPLATE.format(query=quote(address))
    raw = fetch_raw_response_text(url)
    if not raw:
        return None

    # Strip the anti-JSON-hijacking guard prefix Redfin prepends, e.g.
    # '{}&&{"version":648,...}'.
    json_start = raw.find("&&")
    payload_text = raw[json_start + 2:] if json_start != -1 else raw
    try:
        data = json.loads(payload_text)
    except (ValueError, TypeError) as exc:
        logger.warning("Could not parse Redfin autocomplete response for %r: %s", address, exc)
        return None

    payload = data.get("payload", {})
    exact = payload.get("exactMatch")
    if exact and exact.get("url"):
        return exact["url"]

    for section in payload.get("sections", []):
        for row in section.get("rows", []):
            if row.get("url"):
                return row["url"]

    return None


def get_redfin_estimate(address: str) -> dict:
    """
    Look up Redfin's estimate for `address`. Returns
    {"estimate": float | None, "url": str | None} (Phase B.1, 2026-07-13) -
    `url` is the resolved redfin.com/.../home/<id> page, stored separately
    from whether an estimate figure was actually found on it, so the
    investor can always click through to the real listing. `estimate` is
    None if the property couldn't be found, the page was blocked, or no
    estimate is published for it (never fabricated).
    """
    if not address or not address.strip():
        return {"estimate": None, "url": None}

    address = address.strip()
    property_path = _resolve_property_url(address)
    if property_path:
        property_url = "https://www.redfin.com" + property_path
    else:
        # Autocomplete API failed/changed shape - fall back to the same
        # search-engine resolution strategy used by zillow_scraper.py /
        # realtor_scraper.py rather than giving up immediately.
        property_url = resolve_property_url_via_search(
            address, REDFIN_DOMAIN, REDFIN_PATH_PREFIX, REDFIN_URL_PATTERN
        )
        if not property_url:
            logger.info("No Redfin address match found for %r", address)
            return {"estimate": None, "url": None}

    text = fetch_page_text(property_url)
    if not text:
        return {"estimate": None, "url": property_url}

    estimate = extract_dollar_amount_near_label(text, REDFIN_LABELS)
    if estimate is None:
        logger.info("No Redfin Estimate found for address %r at %s", address, property_url)
    return {"estimate": estimate, "url": property_url}
