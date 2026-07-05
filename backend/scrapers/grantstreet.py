"""
grantstreet.py - Adapter stub for the GrantStreet / ClerkAuction platform
used by some Florida county clerks for tax deed / foreclosure sales.

Same honesty rules as realforeclose.py: this adapter makes a real HTTP
attempt (subject to whatever network access is available in the runtime
environment) and only returns parsed records for data it can actually find
in the response. ClerkAuction/GrantStreet sites are also commonly
JS-rendered (React/Angular SPA front-ends calling a JSON API), so a plain
requests.get() + BeautifulSoup parse of the root URL is unlikely to surface
real auction data without first identifying the underlying API endpoint.

No county in config/counties.yaml is currently confirmed to run this
platform (all default placeholders point at realforeclose.com), so this
adapter has NOT been exercised against a real GrantStreet/ClerkAuction URL
during this build. It is included as a ready adapter for when the county
research task confirms a county actually uses this platform.
"""
from datetime import datetime
from typing import Any, Dict

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, ScrapeResult


class GrantStreetScraper(BaseScraper):
    """Scraper adapter for GrantStreet/ClerkAuction county portals."""

    def scrape(self, county_config: Dict[str, Any]) -> ScrapeResult:
        county = county_config.get("county", "UNKNOWN")
        portal_url = county_config.get("portal_url")

        if not portal_url:
            return ScrapeResult(
                success=False,
                error_message=f"No portal_url configured for county '{county}'.",
            )

        try:
            resp = self.get_with_retry(portal_url)
        except Exception as exc:
            return ScrapeResult(
                success=False,
                error_message=(
                    f"HTTP request to {portal_url} failed: {exc}. "
                    "Could be network/DNS/proxy restriction, site downtime, "
                    "or anti-bot blocking. Not scraped."
                ),
            )

        if resp.status_code != 200:
            return ScrapeResult(
                success=False,
                error_message=(
                    f"Non-200 response from {portal_url}: HTTP {resp.status_code}. "
                    "Not scraped."
                ),
            )

        soup = BeautifulSoup(resp.text, "html.parser")
        candidate_rows = soup.select("table tr")

        parsed_records = []
        for row in candidate_rows:
            text = row.get_text(strip=True)
            if text and any(ch.isdigit() for ch in text) and ("/" in text or "-" in text):
                parsed_records.append({
                    "county": county,
                    "raw_row_text": text,
                    "source_url": portal_url,
                    "scraped_at": datetime.utcnow().isoformat(),
                })

        if not parsed_records:
            return ScrapeResult(
                success=False,
                records=[],
                error_message=(
                    "JS-rendered / requires headless browser - not scraped, "
                    "manual verification required. GrantStreet/ClerkAuction "
                    "portals typically render sale data via a client-side "
                    "SPA calling a JSON API; the underlying API endpoint "
                    "must be identified and confirmed against the real "
                    "site before this adapter can reliably extract data."
                ),
            )

        return ScrapeResult(success=True, records=parsed_records, error_message=None)
