"""
flood_zone.py - real FEMA flood zone lookup by address (Phase C.2,
2026-07-13). Replaces the honest "unknown / verify manually" placeholder
that used to be the only possible outcome (see scoring.py's previous
get_flood_zone_info, which never had a working zone-by-point query wired
up).

Two-step lookup, both against free public government APIs, no key needed:
  1. Geocode the address to (lat, lng) via geocode.py (Census Geocoder).
  2. Query FEMA's National Flood Hazard Layer (NFHL) ArcGIS REST map
     service for the flood zone polygon containing that point:
       https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer/28/query
     Layer 28 ("Flood Hazard Zones") is FEMA's own documented layer ID for
     this dataset in the public NFHL service. Returns FLD_ZONE (e.g. "AE",
     "X", "VE") and ZONE_SUBTY (e.g. "0.2 PCT ANNUAL CHANCE FLOOD HAZARD").

NOT independently live-verified from this dev environment: this sandbox's
network egress is restricted to a narrow allowlist (confirmed separately -
even pypi.org and generic github.com are blocked here), and a direct fetch
of hazards.fema.gov returned empty/no response through this session's
tooling, so the exact live JSON shape below could not be confirmed
end-to-end the way geocode.py's Census Geocoder call was. The query is
built directly from FEMA's own documented ArcGIS REST API contract
(https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer,
a standard, widely-used public endpoint with no key requirement) and fails
safe: any non-200 response, unexpected JSON shape, or request error results
in "unknown / verify manually" rather than a guessed zone. Verify live
once deployed (Railway has full network access, unlike this dev sandbox).

Never fabricates a flood zone - returns the honest placeholder on any
failure at any step.
"""
import logging
from typing import Any, Dict, Optional

import requests

from scrapers.geocode import geocode_address

logger = logging.getLogger("scrapers.flood_zone")

NFHL_QUERY_URL = (
    "https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer/28/query"
)
TIMEOUT_SECONDS = 15

UNKNOWN = "unknown / verify manually"


def get_flood_zone(address: str) -> Dict[str, Any]:
    """
    Returns a dict:
      {
        "flood_zone": str,           # e.g. "AE", "X", or UNKNOWN
        "zone_subtype": str | None,  # e.g. "0.2 PCT ANNUAL CHANCE FLOOD HAZARD"
        "source": str,               # human-readable provenance note
        "latitude": float | None,
        "longitude": float | None,
      }
    Never raises; every failure path returns flood_zone=UNKNOWN with a
    `source` explaining why, rather than guessing.
    """
    coords = geocode_address(address)
    if not coords:
        return {
            "flood_zone": UNKNOWN,
            "zone_subtype": None,
            "source": "not attempted - address could not be geocoded (Census Geocoder found no match)",
            "latitude": None,
            "longitude": None,
        }
    lat, lng = coords

    try:
        resp = requests.get(
            NFHL_QUERY_URL,
            params={
                "geometry": f"{lng},{lat}",
                "geometryType": "esriGeometryPoint",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "FLD_ZONE,ZONE_SUBTY",
                "returnGeometry": "false",
                "f": "json",
            },
            timeout=TIMEOUT_SECONDS,
            headers={"User-Agent": "foreclosure-auction-app/1.0 (research tool)"},
        )
        if resp.status_code != 200:
            logger.info("FEMA NFHL query returned HTTP %d for %r", resp.status_code, address)
            return {
                "flood_zone": UNKNOWN,
                "zone_subtype": None,
                "source": f"FEMA NFHL query failed (HTTP {resp.status_code})",
                "latitude": lat,
                "longitude": lng,
            }
        data = resp.json()
        features = data.get("features", [])
        if not features:
            # A real "not in a mapped flood zone" area (common for zone X,
            # which FEMA sometimes omits from the polygon layer entirely)
            # looks identical to a query miss here - report honestly as
            # unmapped rather than guessing "X".
            return {
                "flood_zone": UNKNOWN,
                "zone_subtype": None,
                "source": "FEMA NFHL query succeeded but returned no flood zone polygon for this point (may be an unmapped/non-SFHA area - verify manually)",
                "latitude": lat,
                "longitude": lng,
            }
        attrs = features[0].get("attributes", {})
        zone = attrs.get("FLD_ZONE")
        subtype = attrs.get("ZONE_SUBTY")
        if not zone:
            return {
                "flood_zone": UNKNOWN,
                "zone_subtype": None,
                "source": "FEMA NFHL query returned a feature with no FLD_ZONE attribute",
                "latitude": lat,
                "longitude": lng,
            }
        return {
            "flood_zone": zone,
            "zone_subtype": subtype,
            "source": "FEMA National Flood Hazard Layer (NFHL), hazards.fema.gov",
            "latitude": lat,
            "longitude": lng,
        }
    except Exception as exc:
        logger.warning("FEMA NFHL query failed for %r: %s", address, exc)
        return {
            "flood_zone": UNKNOWN,
            "zone_subtype": None,
            "source": f"FEMA NFHL request error: {exc}",
            "latitude": lat,
            "longitude": lng,
        }
