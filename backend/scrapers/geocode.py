"""
geocode.py - address -> (lat, lng) via the U.S. Census Bureau's free public
Geocoder API (no key required). Used by flood_zone.py (FEMA's NFHL lookup
needs a coordinate, not an address) and to store latitude/longitude on the
Property record so the frontend can link out to the USFWS Wetlands Mapper
centered on the right spot.

REAL VERIFICATION LOG (2026-07-13): confirmed live and reachable from this
dev sandbox (unlike realforeclose.com/zillow.com/etc., which are blocked
here) - a real request against
  https://geocoding.geo.census.gov/geocoder/locations/onelineaddress
for "17915 SAINT CROIX IS TAMPA FL 33647" returned a real match:
  {"addressMatches":[{"coordinates":{"x":-82.297078405397,"y":28.133293340837},
    "matchedAddress":"17915 SAINT CROIX ISLE DR, TAMPA, FL, 33647", ...}]}
Note the API returns x=longitude, y=latitude (GIS convention), not
(lat, lng) order - a common source of bugs, called out explicitly below.

Never fabricates a coordinate: returns None if the address doesn't match
anything, the request fails, or the response can't be parsed.
"""
import logging
from typing import Optional, Tuple

import requests

logger = logging.getLogger("scrapers.geocode")

GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
TIMEOUT_SECONDS = 10


def geocode_address(address: str) -> Optional[Tuple[float, float]]:
    """
    Returns (latitude, longitude) for `address`, or None if it can't be
    geocoded (never fabricated - no fallback centroid/guess).
    """
    if not address or not address.strip():
        return None
    try:
        resp = requests.get(
            GEOCODER_URL,
            params={
                "address": address.strip(),
                "benchmark": "Public_AR_Current",
                "format": "json",
            },
            timeout=TIMEOUT_SECONDS,
            headers={"User-Agent": "foreclosure-auction-app/1.0 (research tool)"},
        )
        if resp.status_code != 200:
            logger.info("Census geocoder returned HTTP %d for %r", resp.status_code, address)
            return None
        data = resp.json()
        matches = data.get("result", {}).get("addressMatches", [])
        if not matches:
            logger.info("Census geocoder found no match for %r", address)
            return None
        coords = matches[0].get("coordinates", {})
        lng = coords.get("x")
        lat = coords.get("y")
        if lat is None or lng is None:
            return None
        return (float(lat), float(lng))
    except Exception as exc:
        logger.warning("Census geocoder request failed for %r: %s", address, exc)
        return None
