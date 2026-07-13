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

REAL VERIFICATION LOG (2026-07-05, live production deployment):
  After the first live scrape (192 Hillsborough records), a real-browser
  inspection of hillsborough.realforeclose.com surfaced two correctness
  bugs in the version above, both confirmed via direct DOM inspection of a
  live day (07/10/2026, a 15-active/18-scheduled day per the calendar):

  1. **Mixing in closed/canceled auctions as if they were upcoming.**
     `.AUCTION_ITEM` matches items in TWO separate containers on the page:
     `#Area_W` ("Auctions Waiting" - the real upcoming/active auctions) and
     `#Area_C` ("Auctions Closed or Canceled" - already-resolved sales).
     The original selector (`.AUCTION_ITEM` with no scoping) grabbed both,
     so already-closed/canceled sales were being written into the Property
     table indistinguishable from real upcoming auctions. Fixed by tagging
     each extracted item with whether it's inside `#Area_C` and dropping
     those before they're ever added to `all_records`.
  2. **No pagination handling - silently dropping records past page 1.**
     The "Auctions Waiting" list paginates (a `.Head_W` widget with
     `#curPWA` = current page number (`curpg` attribute), `#maxWA` = total
     page count, and a `.PageRight` control that AJAX-updates the item list
     in place - confirmed live: clicking it swapped in 5 new AITEM_* ids
     with zero network navigation, URL unchanged). The original adapter
     only ever read whatever was on page 1. On 07/10/2026 that meant 10 of
     15 real active auctions were captured and 5 were silently missed - on
     higher-volume days (the real calendar shows some days with 15-18+
     scheduled) this could mean losing the majority of a day's listings.
     Fixed with a bounded pagination loop: read `#maxWA`, click `.PageRight`
     and wait for `#curPWA`'s `curpg` attribute to advance until it reaches
     `#maxWA`, extracting `#Area_W .AUCTION_ITEM` fresh on every page and
     deduping by `_aid` (AITEM_* ids are unique per item, not per page).
     Capped at MAX_PAGES_PER_DAY to guarantee termination if the site's
     pagination behaves unexpectedly (never an infinite loop).

  Both fixes are defensive rather than assuming this exact DOM forever:
  if `#Area_W`/`#Area_C`/`#curPWA`/`#maxWA` aren't present on some page
  variant (e.g. a realtaxdeed.com county renders slightly differently),
  the code falls back to the pre-fix behavior (grab whatever `.AUCTION_ITEM`
  exists on the single loaded page) rather than raising or returning zero
  records outright.

REAL VERIFICATION LOG (2026-07-13, Phase 1 coverage audit):
  Investigated a user report that many properties were still missing
  (~1,068 in DB across 14 counties). Live-compared each county's real
  RealAuction calendar against `GET /api/properties?county=X` for
  Hillsborough, Orange, and Polk (the three counties named in the audit
  spec), then swept the remaining 11 counties' live DOM once the root
  cause below was found, to see how widely it applied.

  **Root cause found: Orange County returns 0 properties in the DB despite
  `last_scrape_success: true` and no logged error, while its live calendar
  shows dozens of real scheduled sales (e.g. 24/28 FC on 07/14/2026).**
  Confirmed via direct JS execution against the live
  orange.realforeclose.com preview page: Orange's RealAuction template
  renders the label/value widget as a flat `div.ad_tab` containing
  alternating `div.AD_LBL` / `div.AD_DTA` children with NO `<table>`/`<tr>`
  wrapper - every other one of the 14 counties checked this session
  (Hillsborough, Pinellas, Pasco, Hernando, Manatee, Sarasota, Osceola,
  Seminole, Lake, Volusia, Brevard, Marion - Orange is the only exception
  found) uses `table.ad_tab` with `<tr>` rows, which is what the extraction
  JS was hard-coded to require (`table.ad_tab tr`). On Orange's page that
  selector matched zero rows, so every `.AUCTION_ITEM` was found (satisfying
  the scraper's own success check, since `all_records` ends up non-empty)
  but produced an empty `_pairs` list - no `case_number` was ever extracted,
  and `_upsert_scraped_properties` in main.py silently skips any record
  without a case_number (`if not case_number: continue`), so the DB write
  step had nothing to write. Net effect: a real, confirmed-live gap of an
  entire county's worth of properties (dozens per week) with zero visible
  error anywhere in the system - not a demo-data or lookahead-window issue.
  Fixed by pairing `.AD_LBL`/`.AD_DTA` elements directly in document order
  (scoped to whatever tag the `.ad_tab` container is) instead of requiring
  a `<tr>` grouping - verified against both the table-based (Hillsborough)
  and div-based (Orange) live DOM structures with the exact same code path.

  Also checked as part of this audit and confirmed NOT to be a problem:
  `DEFAULT_LOOKAHEAD_DAYS=45` - RealAuction's own calendar for Hillsborough/
  Orange/Polk does not populate sales more than a few weeks out in practice
  (spot-checked live), so 45 days of headroom is not currently cutting
  anything off. Pagination (`#curPWA`/`#maxWA`/`.PageRight`) was confirmed
  live on a real 3-page day (Orange, 07/14/2026, 24 active items across 3
  pages of ~10) and worked correctly. `#Area_W`-only scoping was present
  and correct on every county checked (all had `#Area_W`/`#Area_C`, no
  county rendered waiting auctions in a differently-id'd container).
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

# Hard cap on pagination clicks per day, purely as a termination guarantee -
# real Hillsborough days observed so far top out at 2 pages (~15-18 items),
# so this leaves generous headroom without risking an infinite loop if the
# site's pagination ever behaves unexpectedly (e.g. curpg stops advancing).
MAX_PAGES_PER_DAY = 20

_EXTRACT_ITEMS_JS = """
(items) => items.map(item => {
    const rec = {};
    // .Astat_DATA holds the value in this status widget - what it MEANS
    // depends on the sibling label (.ASTAT_MSGA / .ASTAT_LBL): "Auction
    // Starts" -> the value is a sale date/time; "Auction Status" -> the
    // value is a cancellation reason (confirmed live 2026-07-06, e.g.
    // "Canceled per County" on a #Area_C item). Capturing the label lets
    // the Python side tell these two cases apart rather than trying (and
    // failing) to parse a reason string as a date.
    const statDivs = item.querySelectorAll('.Astat_DATA');
    rec._auction_start_raw = statDivs.length ? statDivs[0].textContent.trim() : null;
    const statLabelEl = item.querySelector('.ASTAT_MSGA, .ASTAT_LBL');
    rec._status_label = statLabelEl ? statLabelEl.textContent.trim() : null;
    rec._aid = item.getAttribute('aid') || item.id;
    rec._in_closed_area = !!item.closest('#Area_C');
    // REAL VERIFICATION LOG (2026-07-13, live coverage audit): confirmed via
    // Chrome DOM inspection that Orange County's RealAuction template
    // renders the label/value widget as a flat `div.ad_tab` containing
    // alternating `div.AD_LBL` / `div.AD_DTA` children with NO `<table>`/
    // `<tr>` wrapper at all - unlike Hillsborough/Pinellas/Pasco/Hernando/
    // Manatee/Sarasota/Osceola/Seminole/Lake/Volusia/Brevard/Marion (all
    // confirmed live this session to use `table.ad_tab` with `<tr>` rows).
    // The old `table.ad_tab tr`-scoped selector matched ZERO rows on
    // Orange's page, so every item there silently produced an empty
    // `_pairs` list (no case_number extracted) even though `.AUCTION_ITEM`
    // divs themselves were found (satisfying the scraper's "success" check)
    // - the net effect was every Orange record being silently dropped in
    // `_upsert_scraped_properties` (case_number required to dedupe/insert)
    // with zero indication anywhere (no error, `last_scrape_success: true`).
    // Fixed by pairing off `.AD_LBL`/`.AD_DTA` elements directly in document
    // order (scoped to the `.ad_tab` container, whatever tag it is) instead
    // of requiring a `<tr>` grouping - this works identically for both the
    // table-based and div-based template variants.
    const pairEls = item.querySelectorAll('.ad_tab .AD_LBL, .ad_tab .AD_DTA');
    let lastLabel = null;
    const pairs = [];
    pairEls.forEach(el => {
        const text = el.textContent.trim();
        if (el.classList.contains('AD_LBL')) {
            if (text) {
                lastLabel = text;
                pairs.push([text, '']);
            }
            // an empty label cell is a continuation row (e.g. address line
            // 2) - keep lastLabel so the following AD_DTA attaches below.
        } else if (pairs.length && lastLabel) {
            const last = pairs[pairs.length - 1];
            last[1] = (last[1] ? last[1] + ' ' : '') + text;
        }
    });
    rec._pairs = pairs;
    return rec;
})
"""


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


def _build_record(
    item: Dict[str, Any], county: str, url: str, canceled: bool
) -> Dict[str, Any]:
    """
    Build a scraped-property record dict from one extracted auction item
    (see _EXTRACT_ITEMS_JS). Shared by both the active (#Area_W) and
    closed/canceled (#Area_C) extraction passes in scrape() so the
    label/field mapping logic isn't duplicated between them.

    For active items, `.Astat_DATA`'s value is a sale date/time
    ("Auction Starts"). For canceled items it's instead a cancellation
    reason string ("Auction Status", e.g. "Canceled per County") -
    confirmed live 2026-07-06. `canceled` tells this function which
    interpretation applies so a reason string is never mis-parsed as (or
    silently discarded in favor of) a sale date, and vice versa.
    """
    record: Dict[str, Any] = {
        "county": county,
        "source_item_id": item.get("_aid"),
        "source_url": url,
        "scraped_at": datetime.utcnow().isoformat(),
        "raw_fields": {},
        "auction_status": "canceled" if canceled else "active",
    }
    if canceled:
        record["cancellation_reason"] = item.get("_auction_start_raw")
        record["sale_date_raw"] = None
        record["sale_date"] = None
    else:
        record["cancellation_reason"] = None
        record["sale_date_raw"] = item.get("_auction_start_raw")
        record["sale_date"] = _parse_auction_start(record["sale_date_raw"])

    for lbl, val in item.get("_pairs", []):
        field = LABEL_FIELD_MAP.get(lbl)
        if field:
            record[field] = _parse_money(val) if field in MONEY_FIELDS else val
        else:
            record["raw_fields"][lbl] = val
    return record


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

                        seen_aids = set()
                        day_had_extraction_error = False

                        for page_num in range(1, MAX_PAGES_PER_DAY + 1):
                            try:
                                # Prefer scoping to #Area_W (the real "Auctions
                                # Waiting" list) so already-closed/canceled
                                # items in #Area_C are never mistaken for
                                # upcoming auctions. Falls back to the
                                # unscoped selector if #Area_W isn't present
                                # on this page variant (defensive, see
                                # REAL VERIFICATION LOG above).
                                if page.query_selector("#Area_W"):
                                    item_selector = "#Area_W .AUCTION_ITEM"
                                else:
                                    item_selector = ".AUCTION_ITEM"
                                page_records = page.eval_on_selector_all(
                                    item_selector, _EXTRACT_ITEMS_JS
                                )
                            except Exception as exc:
                                errors.append(f"{date_str} page {page_num}: DOM extraction failed ({exc})")
                                day_had_extraction_error = True
                                break

                            new_this_page = 0
                            for item in page_records:
                                if item.get("_in_closed_area"):
                                    continue  # belt-and-suspenders even when item_selector was the unscoped fallback
                                aid = item.get("_aid")
                                if aid and aid in seen_aids:
                                    continue  # already captured on an earlier page
                                if aid:
                                    seen_aids.add(aid)
                                new_this_page += 1
                                all_records.append(
                                    _build_record(item, county, url, canceled=False)
                                )

                            # Pagination: #curPWA (curpg attribute) / #maxWA
                            # give current/total page counts for the Waiting
                            # list specifically. If they're not present (no
                            # pagination widget rendered - e.g. a single-page
                            # day, or a page variant without this control),
                            # there's nothing more to page through.
                            max_page_el = page.query_selector("#maxWA")
                            cur_page_el = page.query_selector("#curPWA")
                            if not max_page_el or not cur_page_el:
                                break
                            try:
                                max_page = int((max_page_el.text_content() or "1").strip())
                                cur_page = int(cur_page_el.get_attribute("curpg") or "1")
                            except ValueError:
                                break
                            if cur_page >= max_page:
                                break

                            next_btn = page.query_selector(".Head_W .PageRight")
                            if not next_btn:
                                break
                            next_btn.click()
                            try:
                                page.wait_for_function(
                                    f"document.querySelector('#curPWA') && "
                                    f"document.querySelector('#curPWA').getAttribute('curpg') == '{cur_page + 1}'",
                                    timeout=8000,
                                )
                            except Exception:
                                # Pagination click didn't advance as expected -
                                # stop rather than risk looping on a stuck page
                                # or re-scraping the same page indefinitely.
                                errors.append(
                                    f"{date_str}: pagination stalled after page {page_num} "
                                    f"(expected to reach page {cur_page + 1} of {max_page})"
                                )
                                break

                        # Closed/canceled auctions (#Area_C): confirmed live
                        # 2026-07-06 that these are NOT simply "gone" - the
                        # site keeps them listed with an explicit "Auction
                        # Status" / reason (e.g. "Canceled per County"), and
                        # per investor feedback that reason should be shown
                        # in the app rather than the listing just vanishing.
                        # No pagination widget was found on #Area_C in live
                        # testing, so this is a single one-shot extraction
                        # (unlike #Area_W above) - defensive try/except so a
                        # missing/changed #Area_C never breaks the rest of
                        # the day's scrape.
                        try:
                            closed_records = page.eval_on_selector_all(
                                "#Area_C .AUCTION_ITEM", _EXTRACT_ITEMS_JS
                            )
                        except Exception:
                            closed_records = []
                        for item in closed_records:
                            aid = item.get("_aid")
                            if aid and aid in seen_aids:
                                continue
                            if aid:
                                seen_aids.add(aid)
                            all_records.append(
                                _build_record(item, county, url, canceled=True)
                            )

                        if day_had_extraction_error and not all_records:
                            continue
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
