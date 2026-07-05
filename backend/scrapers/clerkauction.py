"""
UNTESTED STUB - no county in our current list uses this platform; provided
for extensibility only.

GrantStreet/ClerkAuction-style portals are a different product family than
RealForeclose. If a future county is added to counties.yaml with
platform: clerkauction, this adapter would need real implementation and
testing against that specific portal's markup before it could be trusted.
Until then it must never claim success or return fabricated data.
"""
from typing import Any, Dict

from backend.scrapers.base import BaseScraper, ScrapeResult


class ClerkAuctionScraper(BaseScraper):
    def _fetch(self, county_config: Dict[str, Any]) -> ScrapeResult:
        return ScrapeResult(
            success=False,
            records=[],
            error_message="ClerkAuction adapter is an untested stub, not implemented.",
            records_found=0,
        )
