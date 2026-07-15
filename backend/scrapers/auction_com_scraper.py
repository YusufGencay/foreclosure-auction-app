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

get_auction_com_url() therefore always returns None; the frontend's
Auction.com button always links to the bare homepage
(https://www.auction.com/) rather than a guessed deep-link path. If a
future session gets past the CAPTCHA wall (e.g. the user provides a
logged-in/whitelisted session), this module is the place to add real
resolution logic - but never by automating past the challenge itself.
"""
from typing import Optional

AUCTION_COM_HOMEPAGE = "https://www.auction.com/"


def get_auction_com_url(address: str) -> Optional[str]:
    """
    Always returns None (see module docstring) - auction.com is walled
    behind an Imperva/hCaptcha challenge this session couldn't and
    wouldn't attempt to pass. Callers should fall back to
    AUCTION_COM_HOMEPAGE, never a guessed deep link.
    """
    return None
