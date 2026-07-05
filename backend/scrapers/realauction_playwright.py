"""
realauction_playwright.py - Headless-browser adapter for the RealAuction
family of platforms (realforeclose.com / realtaxdeed.com), which serves
13 of the 14 counties in config/counties.yaml.

REAL VERIFICATION LOG (2026-07-04):
  Verified live, logged-out, against https://hillsborough.realforeclose.com
  via a real browser session (not this sandbox - this sandbox's egress
  proxy blocks *.realforeclose.com/*.realtaxdeed.com with
  "blocked-by-allowlist", same restriction noted in realforeclose.py).

  Findings from that real session:
  - The auction calendar lives at
      {portal_url}/index.cfm?zaction=USER&zmethod=CALENDAR
    and the per-day listing ("Preview Items For Sale") lives at
      {portal_url}/index.cfm?zaction=AUCTION&Zmethod=PREVIEW&AUCTIONDATE=MM/DD/YYYY
  - Neither page's item data is present in the raw HTML document (confirmed
    via `fetch(location.href)` from the page itself returning HTML with NO
    case numbers/addresses present) - the page bootstraps a session via an
    internal AJAX handshake (zaction=AUCTION&Zmethod=UPDATE&FNC=LOAD then
    FNC=UPDATE&ref=<internal item ids>) that only works within a real
    browser session that has actually loaded the page (a bare `fetch` replay
    of the same UPDATE URL from a fresh context returned an empty
    `{"retHTML":"","rlist":""}`). This confirms the original realforeclose.py
    docstring's prediction that a plain requests.get() cannot see this data -
    a real rendering engine (Playwright) is required, which is what this
    adapter uses.
  - Once rendered, each auction item is a `div.AUCTION_ITEM` containing:
      - an "Auction Starts" timestamp in `.Astat_DATA` (first occurrence)
      - a `table.ad_tab` of label/value pairs in `td.AD_LBL` / `td.AD_DTA`,
        e.g. "Case #:", "Final Judgment Amount:" (or "Opening Bid:" on some
        tax-deed variants), "Parcel ID:", "Property Address:",
        "Assessed Value:", "Plaintiff Max Bid:".
    This structure was confirmed identical on pinellas.realtaxdeed.com
    (same white-label RealAuction/Realauction.com LLC product), so one
    adapter is expected to work across all realforeclose/realtaxdeed
    counties in counties.yaml, though label sets can vary slightly by
    sale type (foreclosure vs. tax deed) - this adapter reads whatever
    label/value pairs actually exist rather than assuming a fixed set.

  What this page does NOT expose (never fabricated, left null):
  - plaintiff name/type, occupancy status, lien priority / senior-lien
    status, taxes owed, code liens, HOA balance, bankruptcy flag, flood
    zone, market value / comps. These require separate data sources
    (county recorder/appraiser records, title search, FEMA, MLS) that are
    out of scope for this listing-page scraper. `notes` on the resulting
    record says so explicitly so the UI never implies more than what was
    actually scraped.

  Because Playwright's browser binaries need to actually run (real
  Chromium process), this adapter could not be exercised end-to-end in
  this sandbox (network + arguably Playwright is bulky). It has been
  written directly from the real DOM structure captured above and
  covered by a fixture-based unit test using a saved static HTML snapshot
  of one real AUCTION_ITEM (see tests/test_realauction_playwright.py).
  Full live verification should happen once deployed to an environment
  with real network access (see PROJECT_CONTEXT.md deployment plan).
"""
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from scrapers.base import BaseScraper, ScrapeResult

# How many calendar days ahead to check per county per scrape. RealAuction
# calendars are typically populated a few weeks out; 45 gives headroom
# without scanning indefinitely. Configurable via county_config if needed.
DEFAULT_LOOKAHEAD_DAYS = 45


def _parse_money(text: Optional[str]) -> Optional[float]:
    """Parse a $ amount like '$216,465.96' -> 216465.96. Returns None (never
    a fabricated number) if the text isn't a parseable dollar figure, e.g.
    'Hidden' for Plaintiff Max Bid."""
    if not text:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    if not cleaned or cleaned in ("-", "."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_auction_start(raw: Optional[str]) -> Optional[datetime]:
    """Parse '07/20/2026 10:00 AM ET' -> datetime. Returns None if the format
    doesn't match rather than guessing."""
    if not raw:
        return None
    cleaned = raw.replace("ET", "").replace("EST", "").replace("EDT", "").strip()
    for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


# Known label -> structured field mapping. Labels not in this map are kept
# under raw_fields so nothing observed on the page is silently dropped.
LABEL_FIELD_MAP = {
    "Auction Type:": "auction_type",
    "Case #:": "case_number",
    "Final Judgment Amount:": "final_judgment",
    "Opening Bid:": "opening_bid",
    "Parcel ID:": "parcel_id",
    "Property Address:": "address",
    "Assessed Value:": "assessed_value",
    "Plaintiff Max Bid:": "plaintiff_max_bid_raw",
}

MONEY_FIELDS = {"final_judgment", "opening_bid", "assessed_value"}


class RealAuctionPlaywrightScraper(BaseScraper):
    """Headless-browser adapter for realforeclose.com / realtaxdeed.com."""

    def scrape(self, county_config: Dict[str, Any]) -> ScrapeResult:
        county = county_config.get("county", "UNKNOWN")
        portal_url = (county_config.get("portal_url") or "").rstrip("/")
        lookahead_days = int(county_config.get("lookahead_days", DEFAULT_LOOKAHEAD_DAYS))

        if not portal_url:
            return ScrapeResult(
                success=False,
                error_message=f"No portal_url configured for county '{county}'.",
            )

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return ScrapeResult(
                success=False,
                error_message=(
                    "playwright package not installed / browser binaries not "
                    "provisioned (`pip install playwright && playwright install "
                    "--with-deps chromium`). Not scraped."
                ),
            )

        all_records: List[Dict[str, Any]] = []
        errors: List[str] = []

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    page = browser.new_page(user_agent=self.USER_AGENT)
                    page.set_default_timeout(self.TIMEOUT_SECONDS * 1000)

                    today = datetime.utcnow().date()
                    for offset in range(lookahead_days):
                        day = today + timedelta(days=offset)
                        date_str = day.strftime("%m/%d/%Y")
                        url = (
                            f"{portal_url}/index.cfm?zaction=AUCTION&Zmethod=PREVIEW"
                            f"&AUCTIONDATE={date_str}"
                        )
                        self._respect_rate_limit()
                        self._last_request_time = time.monotonic()

                        try:
                            page.goto(url, wait_until="networkidle")
                        except Exception as exc:
                            errors.append(f"{date_str}: navigation failed ({exc})")
                            continue

                        try:
                            page.wait_for_selector(
                                ".AUCTION_ITEM, .no-auction, body", timeout=8000
                            )
                        except Exception:
                            pass  # fall through; item extraction below just finds 0

                        try:
                            day_records = page.eval_on_selector_all(
                                ".AUCTION_ITEM",
                                """
                                (items) => items.map(item => {
                                    const rec = {};
                                    const statDivs = item.querySelectorAll('.Astat_DATA');
                                    rec._auction_start_raw = statDivs.length ? statDivs[0].textContent.trim() : null;
                                    rec._aid = item.getAttribute('aid');
                                    const rows = item.querySelectorAll('table.ad_tab tr');
                                    let lastLabel = null;
                                    const pairs = [];
                                    rows.forEach(r => {
                                        const lbl = r.querySelector('.AD_LBL');
                                        const dta = r.querySelector('.AD_DTA');
                                        const lblText = lbl ? lbl.textContent.trim() : '';
                                        const dtaText = dta ? dta.textContent.trim() : '';
                                        if (lblText) {
                                            lastLabel = lblText;
                                            pairs.push([lblText, dtaText]);
                                        } else if (lastLabel && dtaText) {
                                            const last = pairs[pairs.length - 1];
                                            if (last) last[1] = (last[1] + ' ' + dtaText).trim();
                                        }
                                    });
                                    rec._pairs = pairs;
                                    return rec;
                                })
                                """,
                            )
                        except Exception as exc:
                            errors.append(f"{date_str}: DOM extraction failed ({exc})")
                            continue

                        for item in day_records:
                            record: Dict[str, Any] = {
                                "county": county,
                                "sale_date_raw": item.get("_auction_start_raw"),
                                "source_item_id": item.get("_aid"),
                                "source_url": url,
                                "scraped_at": datetime.utcnow().isoformat(),
                                "raw_fields": {},
                            }
                            for lbl, val in item.get("_pairs", []):
                                field = LABEL_FIELD_MAP.get(lbl)
                                if field:
                                    record[field] = (
                                        _parse_money(val) if field in MONEY_FIELDS else val
                                    )
                                else:
                                    record["raw_fields"][lbl] = val
                            record["sale_date"] = _parse_auction_start(
                                record.get("sale_date_raw")
                            )
                            all_records.append(record)
                finally:
                    browser.close()
        except Exception as exc:
            return ScrapeResult(
                success=False,
                records=all_records,
                error_message=(
                    f"Playwright browser session failed for {county}: {exc}. "
                    + ("; ".join(errors) if errors else "")
                ),
            )

        if not all_records:
            return ScrapeResult(
                success=False,
                records=[],
                error_message=(
                    f"No auction items found for {county} across the next "
                    f"{lookahead_days} days. Either genuinely no sales are "
                    "scheduled, or the site's DOM structure changed since "
                    "this adapter was written (expects div.AUCTION_ITEM / "
                    "table.ad_tab - verify manually if sales are expected)."
                    + (f" Navigation errors: {'; '.join(errors)}" if errors else "")
                ),
            )

        return ScrapeResult(success=True, records=all_records, error_message=None)
