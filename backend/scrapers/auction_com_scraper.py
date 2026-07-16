"""
auction_com_scraper.py - Phase 3 (2026-07-15): would resolve a property's
address to its auction.com listing page for a branded link-out button,
same intent as federa_scraper.py. Per the user's 2026-07-13 decision, this
never scrapes an "estimate" from Auction.com - just a best-effort link.

REAL VERIFICATION LOG (2026-07-15, live Chrome session): auction.com's
homepage itself (not even a search page) is walled behind an Imperva
"Additional security check is required" interstitial with an hCaptcha
challenge ("I am human" checkbox) - confirmed live, screenshotted. This
was hit on a plain, unauthenticated page load, before any search or
automation was attempted.

This module deliberately does NOT attempt to solve, click through, or
otherwise work around that CAPTCHA/bot-detection challenge - completing a
CAPTCHA programmatically is out of scope for this project on principle,
not just because automation would likely fail anyway. As a direct
consequence, no address-resolution logic was written here at all: there
was no way to even reach a search page to learn its URL/query-param
pattern this session (the spec's own fallback instruction - "verify live
that the query param actually pre-fills" - couldn't be attempted because
the CAPTCHA wall blocks reaching any page past the interstitial).

2026-07-16 UPDATE: a user reported this button never reaches a real
listing - it was always landing on the bare homepage, per the design above.
That's still correct for auction.com's *own* site (never touched directly,
never will be while it's CAPTCHA-walled), but there was a real workaround
available that this session hadn't tried yet: DuckDuckGo's html search
endpoint (html.duckduckgo.com) is a neutral third party, not auction.com
itself, and this codebase already uses it (see
estimate_common.resolve_property_url_via_search) to find real Zillow/
Realtor.com listing URLs without ever visiting those sites' own search
UIs. The exact same approach works here: query
"site:auction.com <address>" and take whatever real, DuckDuckGo-indexed
auction.com URL comes back, verified against the address's house number
(never a guess) - auction.com's CAPTCHA is never touched, only DuckDuckGo
is queried. If no confident match is found, this still returns None and
the caller falls back to AUCTION_COM_HOMEPAGE, exactly as before.
"""
from typing import Optional

from scrapers.estimate_common import resolve_property_url_via_search

AUCTION_COM_HOMEPAGE = "https://www.auction.com/"

# auction.com's real listing-page URL structure was never observed directly
# (the CAPTCHA wall blocks reaching one), so this deliberately does not
# require a specific path prefix like the Zillow/Realtor resolvers do
# (e.g. "/homedetails"). Instead it accepts any auction.com URL with a
# reasonably long path beyond the bare domain (>= 10 chars), which rules out
# matching the homepage itself while still working no matter what auction.com
# actually names its listing paths - the house-number verification inside
# resolve_property_url_via_search is what actually confirms correctness, not
# this pattern.
_AUCTION_COM_URL_PATTERN = r"www\.auction\.com/[a-zA-Z0-9][\w\-/]{10,}"


def get_auction_com_url(address: str) -> Optional[str]:
    """
    Resolves `address` to a real auction.com listing URL via a DuckDuckGo
    site-search (never visits auction.com directly - see module docstring).
    Returns None (caller falls back to AUCTION_COM_HOMEPAGE) if DuckDuckGo
    itself is unreachable/blocked, or no result's context confidently
    matches the address's house number.
    """
    return resolve_property_url_via_search(
        address,
        domain="auction.com",
        path_prefix="",
        url_pattern=_AUCTION_COM_URL_PATTERN,
    )
