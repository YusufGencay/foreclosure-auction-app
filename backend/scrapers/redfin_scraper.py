"""
redfin_scraper.py - on-demand Redfin Estimate lookup for a single property
address. Called by GET /api/properties/{id}/enrich (Phase 1 spec).

See scrapers/estimate_common.py for the shared honesty/rate-limit/timeout
rules this module follows.

REAL VERIFICATION LOG (2026-07-05): the previous version of this module used
`https://www.redfin.com/search?query=...`, which was WRONG - live-checked
via a real Chrome browser and confirmed that URL just redirects to the
Redfin homepage with no search results, meaning this scraper could never
have found real data. Confirmed the actual working flow, live, against
address "17915 Saint Croix Isle Dr, Tampa, FL 33647":

1. GET `https://www.redfin.com/stingray/do/location-autocomplete
   ?location=<address>&v=2` - Redfin's own address-autocomplete API.
   Returns a JSON body prefixed with the anti-JSON-hijacking guard `{}&&`
   (must be stripped before parsing), containing an `exactMatch` (or
   `payload.sections[].rows[]`) object with a `url` field, e.g.
   `/FL/Tampa/17915-Saint-Croix-Isle-Dr-33647/home/47184630`.
2. Navigate to `https://www.redfin.com` + that url. The rendered page
   contains the literal text "Redfin Estimate" followed by a dollar figure
   (confirmed live: "Redfin Estimate $812,676" for the address above).

Fixed to actually perform both steps rather than guessing a single search
URL. Still returns None (never a guessed number) on any failure, blocked
page, no address match, or missing estimate figure.
"""
import json
import logging
import re
from urllib.parse import quote

from scrapers.estimate_common import (
    TIMEOUT_MS,
    USER_AGENT,
    _record_diagnostic,
    extract_dollar_amount_near_label,
    fetch_page_text,
    fetch_raw_response_text,
    normalize_address,
)

logger = logging.getLogger("scrapers.redfin")

REDFIN_HOMEPAGE = "https://www.redfin.com/"

AUTOCOMPLETE_URL_TEMPLATE = (
    "https://www.redfin.com/stingray/do/location-autocomplete"
    "?location={query}&v=2"
)

# Fallback if Redfin's own autocomplete API changes shape or starts
# blocking headless requests: Redfin detail URLs don't share one fixed
# path prefix (they're /<state>/<city>/<slug>/home/<id>), so this pattern
# just requires the distinctive "/home/<digits>" suffix common to all of
# them.
REDFIN_DOMAIN = "redfin.com"
REDFIN_PATH_PREFIX = ""
REDFIN_URL_PATTERN = r"www\.redfin\.com/[\w/\-]+/home/\d+"

REDFIN_LABELS = ["Redfin Estimate"]


def _resolve_via_site_search(address: str) -> str | None:
    """
    Resolve `address` to a real redfin.com/.../home/<id> URL by driving
    Redfin's own visible search box in a real browser session, exactly like
    a human user - the same approach federa_scraper.py already uses
    successfully.

    WHY THIS EXISTS (2026-07-21, measured, not assumed)
    ---------------------------------------------------
    A connectivity probe run FROM the Railway container
    (GET /api/diagnostics/connectivity, see backend/diagnostics.py) showed,
    unambiguously:

      redfin known listing page  => OK (HTTP 200, 891,957 bytes)
      redfin autocomplete API    => REACHABLE BUT REFUSED (HTTP 403)

    That combination is the whole story. Redfin serves us full property
    pages over 800KB of real HTML, from this exact IP, right now - so
    Railway's IP is NOT blocked by Redfin, and reading an estimate off a
    listing page is entirely viable. What fails is only the FIRST step:
    the /stingray/do/location-autocomplete endpoint refuses a bare
    `requests` call (403), because that endpoint expects to be called from
    within a real browser session on redfin.com (cookies, referer, the
    session state a normal page visit establishes) rather than as a
    standalone scripted GET.

    The old code's response to that 403 was to fall through to
    resolve_property_url_via_search(), i.e. DuckDuckGo - which the same
    probe proved is unreachable from Railway at the TCP level
    (ConnectTimeout on html./lite./www. duckduckgo.com alike), as is every
    other free search engine tested (Mojeek 403, Brave/Bing/Startpage/
    Ecosia bot-challenge pages, searx.be 403). So resolution had no working
    path at all, which is why every Redfin estimate in production has been
    null and every "View on Redfin" button has been a bare search fallback.

    This function restores a working path without adding any paid
    dependency: open redfin.com in Playwright, type the address into the
    site's own public search box, and take the URL the site itself
    navigates to. No internal/undocumented endpoint is called directly
    (consistent with this project's standing rule - see
    federa_scraper.py's docstring), no CAPTCHA is bypassed, and nothing is
    fabricated: if the search box can't be found, no suggestion appears, or
    the resulting URL isn't a real /home/<id> page, this returns None and
    the caller reports the estimate as unavailable.

    Diagnostics: failures are recorded via estimate_common's
    _record_diagnostic so they surface in the live /enrich response's
    enrich_errors instead of vanishing into a log nobody can read (the
    2026-07-17 session added that mechanism precisely because silent
    warnings made this class of bug undiagnosable for two sessions).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _record_diagnostic(REDFIN_HOMEPAGE, "playwright not installed")
        return None

    # County scraper output is not directly searchable ("... TAMPA, FL- 33647")
    # - see normalize_address's docstring for the live evidence.
    search_term = normalize_address(address)
    if not search_term:
        return None

    house_number_match = re.match(r"\s*(\d+)", search_term)
    house_number = house_number_match.group(1) if house_number_match else None

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as launch_exc:
                _record_diagnostic(
                    REDFIN_HOMEPAGE,
                    f"BROWSER LAUNCH FAILED: {type(launch_exc).__name__}: {launch_exc}",
                )
                return None
            try:
                page = browser.new_page(user_agent=USER_AGENT)
                page.set_default_timeout(TIMEOUT_MS)
                page.goto(REDFIN_HOMEPAGE, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
                page.wait_for_timeout(2500)

                # Redfin has changed this box's placeholder copy several
                # times ("City, Address, School, Agent, ZIP" historically,
                # shorter variants since). Try a few stable-ish handles in
                # order rather than pinning to one exact string, so a copy
                # tweak degrades to "no result" rather than a hard break.
                # Ordered most-specific-first. The generic get_by_role
                # ("combobox") that used to lead this list matched some
                # other control on the page and silently swallowed the
                # typed address (see the fill-verification block below), so
                # it is now the LAST resort rather than the first choice.
                # IMPORTANT (2026-07-21, confirmed by inspecting the live
                # redfin.com DOM in a real browser): redfin.com renders TWO
                # visible inputs that share the SAME id and name -
                # id="search-box-input" name="searchInputBox" - one being
                # the main hero search box (placeholder "City, Address,
                # School, Agent, ZIP") and one a duplicate with an empty
                # placeholder. Selecting `.first` is therefore ambiguous and
                # was resolving to the wrong element: the address got typed
                # into one box while the autocomplete/Enter handling
                # belonged to the other, so Redfin navigated to its own
                # default suggestion. That is the precise mechanism behind
                # the observed "Tampa address resolved to a Chicago condo"
                # failure.
                #
                # Requiring a non-empty placeholder disambiguates to the
                # real search box. The [placeholder] variants are tried
                # first for exactly this reason - do not reorder them above
                # the bare name/id selectors.
                search_box = None
                for locator in (
                    page.locator('input[name="searchInputBox"][placeholder]:not([placeholder=""])').first,
                    page.locator('#search-box-input[placeholder]:not([placeholder=""])').first,
                    page.locator('input[name="searchInputBox"]').first,
                    page.locator('#search-box-input').first,
                    page.locator('input[data-rf-test-name="search-box-input"]').first,
                    page.locator('input[placeholder*="Address" i]').first,
                    page.locator('input[placeholder*="City" i]').first,
                    page.locator('input[placeholder*="ZIP" i]').first,
                    page.locator('input[type="search"]').first,
                    page.get_by_role("combobox").first,
                ):
                    try:
                        if locator.count() > 0 and locator.is_visible():
                            search_box = locator
                            break
                    except Exception:
                        continue

                if search_box is None:
                    _record_diagnostic(
                        REDFIN_HOMEPAGE,
                        "Redfin search box not found on homepage (page loaded but no "
                        "recognizable search input) - site layout may have changed.",
                    )
                    return None

                search_box.click()
                search_box.fill(search_term)

                # Verify the text actually landed in the box before acting
                # on any suggestion.
                #
                # WHY (2026-07-21, live production evidence): the previous
                # revision typed the address, blindly pressed ArrowDown +
                # Enter, and Redfin navigated to
                # /IL/Chicago/6526-S-Kimbark-Ave-60637/... for a query of
                # "10406 CANARY ISLE DR TAMPA, FL 33647". A Chicago condo is
                # not a near-miss for a Tampa address - it's Redfin's own
                # default/promoted suggestion, which is what the dropdown
                # offers when it has received no query text. In other words
                # the fill() silently went to the wrong element (the first
                # matching "combobox" on the page is not necessarily the
                # property search box) and we then confidently selected
                # whatever happened to be first.
                #
                # Only the house-number guard on the final URL stopped that
                # from being shown to the investor as their property's
                # comp. Checking the input's own value here catches the
                # failure at its source instead of relying on that last
                # line of defense.
                try:
                    typed = (search_box.input_value() or "").strip()
                except Exception:
                    typed = ""
                if house_number and house_number not in typed:
                    _record_diagnostic(
                        REDFIN_HOMEPAGE,
                        f"Search box did not accept the query (expected it to "
                        f"contain {house_number!r}, box contains {typed[:80]!r}) - "
                        f"the located input is probably not Redfin's property "
                        f"search field. Refusing to select a suggestion, since "
                        f"an empty query yields unrelated default results.",
                    )
                    return None

                # Redfin's autocomplete fires as you type; give it time to
                # populate before committing to a selection.
                page.wait_for_timeout(3000)

                # Select the first autocomplete suggestion via the keyboard
                # rather than by CSS selector.
                #
                # WHY (2026-07-21): the first version of this function tried
                # to click a suggestion matched by selectors like
                # [data-rf-test-name="search-autocomplete-item"]. A live
                # production run showed it silently matching nothing and
                # falling through to a bare Enter press, which left the
                # browser sitting on the homepage - the exact failure the
                # diagnostic reported ("did not land on a /home/ detail
                # page (ended at 'https://www.redfin.com/')"). Guessing a
                # third-party site's internal CSS/test attributes is
                # inherently brittle; ArrowDown+Enter is how a keyboard user
                # picks the top suggestion and doesn't depend on Redfin's
                # markup at all.
                #
                # Picking the FIRST suggestion is safe here only because the
                # house-number check on the resulting URL below rejects a
                # wrong-property match outright rather than returning it.
                page.keyboard.press("ArrowDown")
                page.wait_for_timeout(400)
                page.keyboard.press("Enter")
                page.wait_for_timeout(4500)

                url = page.url
                if "/home/" not in (url or ""):
                    # Some queries land on a search-results page instead of
                    # a detail page. If exactly one real listing card is
                    # present, follow it; otherwise give up rather than
                    # picking arbitrarily among several properties.
                    try:
                        links = page.locator('a[href*="/home/"]')
                        if links.count() > 0:
                            href = links.first.get_attribute("href")
                            if href:
                                url = href if href.startswith("http") else "https://www.redfin.com" + href
                    except Exception:
                        pass
            finally:
                browser.close()
    except Exception as exc:
        _record_diagnostic(REDFIN_HOMEPAGE, f"{type(exc).__name__}: {exc}")
        return None

    if url and "/home/" in url:
        if house_number and house_number not in url:
            # The URL slug carries the street number for real detail pages
            # (/FL/Tampa/17915-Saint-Croix-Isle-Dr-33647/home/47184630).
            # A /home/ URL for a DIFFERENT number means the site resolved
            # our query to some other property - refuse it rather than
            # silently linking the investor to the wrong house.
            _record_diagnostic(
                REDFIN_HOMEPAGE,
                f"Redfin resolved {address!r} to {url} but house number "
                f"{house_number!r} is absent from that URL - refusing a "
                f"possible wrong-property match.",
            )
            return None
        return url

    _record_diagnostic(
        REDFIN_HOMEPAGE,
        f"Redfin search for {address!r} did not land on a /home/ detail page "
        f"(ended at {url!r}) - no published listing for this address, or the "
        f"query was ambiguous.",
    )
    return None


def _resolve_property_url(address: str) -> str | None:
    """
    Resolve a free-text address to Redfin's internal property page path
    (e.g. "/FL/Tampa/17915-Saint-Croix-Isle-Dr-33647/home/47184630") via
    Redfin's own autocomplete API. Returns None if no address match is
    found or the API call fails.

    2026-07-21: this endpoint now returns HTTP 403 to a plain scripted
    request from Railway (measured - see _resolve_via_site_search above).
    Kept as the first attempt anyway because it's by far the cheapest path
    when it does work (one HTTP GET vs. launching a whole browser), and a
    403 here is fast to detect; get_redfin_estimate falls back to the
    browser-driven site search when this returns None.
    """
    url = AUTOCOMPLETE_URL_TEMPLATE.format(query=quote(address))
    raw = fetch_raw_response_text(url)
    if not raw:
        return None

    # Strip the anti-JSON-hijacking guard prefix Redfin prepends, e.g.
    # '{}&&{"version":648,...}'.
    json_start = raw.find("&&")
    payload_text = raw[json_start + 2:] if json_start != -1 else raw
    try:
        data = json.loads(payload_text)
    except (ValueError, TypeError) as exc:
        logger.warning("Could not parse Redfin autocomplete response for %r: %s", address, exc)
        return None

    payload = data.get("payload", {})
    exact = payload.get("exactMatch")
    if exact and exact.get("url"):
        return exact["url"]

    for section in payload.get("sections", []):
        for row in section.get("rows", []):
            if row.get("url"):
                return row["url"]

    return None


def get_redfin_estimate(address: str) -> dict:
    """
    Look up Redfin's estimate for `address`. Returns
    {"estimate": float | None, "url": str | None} (Phase B.1, 2026-07-13) -
    `url` is the resolved redfin.com/.../home/<id> page, stored separately
    from whether an estimate figure was actually found on it, so the
    investor can always click through to the real listing. `estimate` is
    None if the property couldn't be found, the page was blocked, or no
    estimate is published for it (never fabricated).
    """
    if not address or not address.strip():
        return {"estimate": None, "url": None}

    address = address.strip()
    property_path = _resolve_property_url(address)
    if property_path:
        property_url = "https://www.redfin.com" + property_path
    else:
        # Autocomplete API failed (currently a hard 403 from Railway - see
        # _resolve_via_site_search). Fall back to driving Redfin's own
        # public search box in a real browser session.
        #
        # NOTE (2026-07-21): this used to fall back to
        # resolve_property_url_via_search(), i.e. DuckDuckGo - which is
        # unreachable from Railway at the TCP level, along with every other
        # free search engine tested. That dead fallback is why Redfin
        # estimates have been null for every property in production. The
        # search-engine path is deliberately NOT used here anymore.
        property_url = _resolve_via_site_search(address)
        if not property_url:
            logger.info("No Redfin address match found for %r", address)
            return {"estimate": None, "url": None}

    text = fetch_page_text(property_url)
    if not text:
        return {"estimate": None, "url": property_url}

    estimate = extract_dollar_amount_near_label(text, REDFIN_LABELS)
    if estimate is None:
        logger.info("No Redfin Estimate found for address %r at %s", address, property_url)
    return {"estimate": estimate, "url": property_url}
