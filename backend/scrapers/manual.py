"""
Adapter for platform: other/manual counties (Hernando, Sarasota, Osceola,
Seminole, Brevard as of this build).

These counties do not have a confirmed automated/scriptable auction portal.
This adapter intentionally makes NO HTTP request and NO attempt to scrape -
it simply reports that manual verification is required, while still
surfacing the portal_url so the UI can link out to it. This keeps these
counties visible in /api/scrape/status without ever risking fabricated or
mis-scraped data.
"""
from typing import Any, Dict

from backend.scrapers.base import BaseScraper, ScrapeResult


class ManualScraper(BaseScraper):
    def _fetch(self, county_config: Dict[str, Any]) -> ScrapeResult:
        return ScrapeResult(
            success=False,
            records=[],
            error_message=(
                "Manual verification required — no automated scraper available "
                "for this portal type. See portal_url for link-out."
            ),
            records_found=0,
        )
