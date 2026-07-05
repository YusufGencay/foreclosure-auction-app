"""
realforeclose.py - Adapter for the RealForeclose / RealAuction platform
(e.g. hillsborough.realforeclose.com, pinellas.realforeclose.com, etc.)

REAL ATTEMPT LOG (recorded during development, 2026-07-03):
  We actually attempted `requests.get("https://hillsborough.realforeclose.com")`
  and several sibling URLs (and even https://www.google.com as a control)
  from this build environment. Every outbound HTTPS request was rejected at
  the sandbox's own egress proxy with:
      HTTP/1.1 403 Forbidden
      X-Proxy-Error: blocked-by-allowlist
  i.e. this dev sandbox has no general internet egress at all (not even
  google.com resolves), so we could not observe RealForeclose's actual
  response in THIS environment. This is a sandbox/allowlist restriction,
  not evidence about RealForeclose itself.

  Separately, it is well documented (and expected from prior experience
  with RealAuction-family sites) that RealForeclose auction calendars are
  rendered client-side via ASP.NET WebForms + heavy JavaScript (the sale
  list is populated by AJAX calls after page load, not present in the raw
  HTML document). A plain `requests.get()` + BeautifulSoup parse of the
  root URL, even when network access succeeds, is very likely to return a
  shell page without the actual auction/property rows.

  Because we cannot fabricate data, this adapter is written defensively:
  it makes a real HTTP attempt through BaseScraper.get_with_retry, and only
  parses fields it can ACTUALLY find in the returned HTML (e.g. obvious
  auction date links/tables, if present). If the expected data is not
  present in the raw HTML (which is the expected/observed situation), it
  returns ScrapeResult(success=False, ...) with a clear, honest
  error_message instead of inventing property records. A production
  deployment of this adapter should be swapped to use a headless browser
  (e.g. Playwright) to render the JS calendar, or a discovered underlying
  JSON/AJAX endpoint, once that is confirmed against the real site.
"""
from datetime import datetime
from typing import Any, Dict

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, ScrapeResult


class RealForecloseScraper(BaseScraper):
    """Scraper adapter for RealForeclose/RealAuction county portals."""

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
        except Exception as exc:  # network/proxy/DNS failure etc.
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
                    "Possible bot-blocking (e.g. WAF/Cloudflare) or portal change. "
                    "Not scraped."
                ),
            )

        soup = BeautifulSoup(resp.text, "html.parser")

        # Best-effort attempt to find a real auction table/list in the raw
        # HTML. RealForeclose calendars are typically JS/AJAX-rendered, so
        # this is expected to find nothing on the root URL in most cases.
        candidate_rows = soup.select("table tr") or soup.select("[class*='auction']")

        parsed_records = []
        for row in candidate_rows:
            text = row.get_text(strip=True)
            if not text:
                continue
            # Extremely conservative heuristic: only treat a row as a real
            # auction-date record if it contains something that looks like
            # a date. We do NOT invent case numbers, prices, or addresses -
            # if the platform's real markup isn't recognized, we skip it.
            if any(ch.isdigit() for ch in text) and ("/" in text or "-" in text):
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
                    "manual verification required. The RealForeclose auction "
                    "calendar for this county did not expose parseable "
                    "auction rows in the raw HTML response (expected, since "
                    "this platform typically loads the sale list via "
                    "client-side JavaScript/AJAX after initial page load)."
                ),
            )

        # If we ever DO find real rows, only real parsed data is returned -
        # never fabricated/enriched fields.
        return ScrapeResult(success=True, records=parsed_records, error_message=None)
