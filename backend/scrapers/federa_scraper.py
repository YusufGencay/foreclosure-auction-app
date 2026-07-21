"""
federa_scraper.py - resolves a property's address to its federa.com listing
page, if one exists, for a branded one-click link-out button. Per the user's
explicit 2026-07-13 decision, this never scrapes an "estimate" off Federa -
Federa doesn't reliably list every county-courthouse sale, so a missing
listing just means no button/a search-page fallback, never a fabricated
figure.

This drives federa.com's own visible search box via Playwright, exactly like
a real user. It does NOT call any of federa.com's internal/undocumented API
endpoints directly (some exist - e.g. `/api/internal/properties/find`,
visible in a network log - but probing undocumented internal endpoints on a
third-party site is deliberately out of scope; see PROJECT_CONTEXT.md).

REAL VERIFICATION LOG (2026-07-21, live interactive Chrome session against
the current site, re-walked step by step because the previous version of
this module had silently stopped working):

  1. federa.com loads cleanly, no CAPTCHA/bot-block, and is reachable from
     Railway (HTTP 200 - confirmed by GET /api/diagnostics/connectivity).
  2. Typing "2035 Hemingway Avenue, Haines City, FL" into the site's search
     box produced a "SUGGESTIONS" dropdown.
  3. Clicking the matching suggestion navigated to
     https://federa.com/property/5f134126-e884-40bf-8c50-76ae1c323b5d

THREE REAL BUGS FOUND IN THE PREVIOUS VERSION (all confirmed against the
live DOM, none of them guesses):

  (1) THE SEARCH BOX IS A <textarea>, NOT AN <input>. The old code used
      page.get_by_placeholder("Search homes"), which is element-type
      agnostic and so still matched - but every mental model and fallback
      built around it assumed an input. Documented here explicitly because
      it is genuinely surprising and will mislead the next reader.

  (2) THERE ARE TWO "Search homes" TEXTAREAS, one visible and one hidden.
      The old code took `.first`, which is ambiguous and can select the
      hidden one - filling an offscreen element that no autocomplete is
      wired to, producing no suggestions and a silent no-match. This is
      the same duplicate-element trap found on redfin.com the same day.
      Now explicitly filtered to the VISIBLE one.

  (3) THE SEARCH BOX RENDERS LATE. On a fresh load, document.querySelectorAll
      ('input,textarea') returned ZERO matches; the textarea only appeared
      after a few seconds of client-side rendering. The old code waited a
      flat 2000ms and then queried once, so on a slow render it would find
      nothing and give up. Now waits for the element to actually exist.

  (4) AMBIGUOUS SUGGESTIONS ARE REAL. The live dropdown for the address
      above offered BOTH "2035 Hemingway Avenue" and "2035 Hemingway
      Circle" - same house number, same street name, different street
      type. Matching on house number alone (the approach used elsewhere in
      this codebase) would have picked whichever came first and could
      easily link the investor to the wrong property. This module now
      requires the street TYPE to disambiguate, and refuses rather than
      guesses when it still can't tell them apart.

Returns None (never a guessed/constructed URL) if no match is found or the
page can't be loaded - the frontend falls back to a plain link to federa.com's
homepage in that case (never a deep-linked guess).
"""
import logging
import re
import time
from typing import Optional

from scrapers.estimate_common import _record_diagnostic, normalize_address

logger = logging.getLogger("scrapers.federa")

TIMEOUT_MS = 30_000
MIN_DELAY_SECONDS = 3.0

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

FEDERA_HOMEPAGE = "https://federa.com/"

# Street-type synonyms, used only to tell apart suggestions that are
# otherwise identical (see bug (4) above: "Hemingway Avenue" vs "Hemingway
# Circle"). County scrapers abbreviate ("AVE"); Federa spells it out
# ("Avenue"), so a literal string compare fails.
STREET_TYPE_SYNONYMS = {
    "ave": "avenue", "avenue": "avenue",
    "st": "street", "street": "street",
    "rd": "road", "road": "road",
    "dr": "drive", "drive": "drive",
    "cir": "circle", "circle": "circle",
    "ln": "lane", "lane": "lane",
    "ct": "court", "court": "court",
    "blvd": "boulevard", "boulevard": "boulevard",
    "pl": "place", "place": "place",
    "ter": "terrace", "terrace": "terrace",
    "trl": "trail", "trail": "trail",
    "pkwy": "parkway", "parkway": "parkway",
    "hwy": "highway", "highway": "highway",
    "way": "way", "loop": "loop", "run": "run", "walk": "walk",
}

_last_request_time: Optional[float] = None


def _respect_rate_limit():
    global _last_request_time
    if _last_request_time is not None:
        elapsed = time.monotonic() - _last_request_time
        wait_for = MIN_DELAY_SECONDS - elapsed
        if wait_for > 0:
            time.sleep(wait_for)
    _last_request_time = time.monotonic()


def _street_type_of(text: str) -> Optional[str]:
    """Canonical street type found in `text`, if any (e.g. "AVE" -> "avenue")."""
    for token in re.findall(r"[A-Za-z]+", text.lower()):
        if token in STREET_TYPE_SYNONYMS:
            return STREET_TYPE_SYNONYMS[token]
    return None


def _pick_matching_suggestion(candidates, address: str):
    """
    Choose the suggestion that unambiguously matches `address`.

    Requires the house number to match, then uses the street type to break
    ties. Returns None when the result would be a guess - a wrong link here
    sends an investor to the wrong house's numbers, so refusing is strictly
    better than picking plausibly.
    """
    house_match = re.match(r"\s*(\d+)", address.strip())
    house_number = house_match.group(1) if house_match else None
    if not house_number:
        return None

    # Keep only suggestions carrying this exact house number.
    matches = [
        c for c in candidates
        if re.search(rf"\b{re.escape(house_number)}\b", c["text"])
    ]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    # Ambiguous (the real "Avenue vs Circle" case) - disambiguate on type.
    wanted_type = _street_type_of(address)
    if wanted_type:
        typed = [m for m in matches if _street_type_of(m["text"]) == wanted_type]
        if len(typed) == 1:
            return typed[0]

    logger.info(
        "Federa: %d suggestions matched house number %r for %r and street type "
        "could not disambiguate them - refusing to guess.",
        len(matches), house_number, address,
    )
    return None


def get_federa_url(address: str) -> Optional[str]:
    """
    Resolve `address` to a real federa.com/property/<id> URL by driving the
    site's own public search box. Returns None on any failure or no-match -
    never guesses a URL.
    """
    if not address or not address.strip():
        return None

    # County scraper output ("... TAMPA, FL- 33647") is not directly
    # searchable - see normalize_address in estimate_common.
    search_term = normalize_address(address)
    if not search_term:
        return None

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _record_diagnostic(FEDERA_HOMEPAGE, "playwright not installed")
        return None

    _respect_rate_limit()

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as launch_exc:
                _record_diagnostic(
                    FEDERA_HOMEPAGE,
                    f"BROWSER LAUNCH FAILED: {type(launch_exc).__name__}: {launch_exc}",
                )
                return None
            try:
                page = browser.new_page(user_agent=USER_AGENT)
                page.set_default_timeout(TIMEOUT_MS)
                page.goto(FEDERA_HOMEPAGE, wait_until="domcontentloaded", timeout=TIMEOUT_MS)

                # The search box renders client-side, well after
                # domcontentloaded - see bug (3). Wait for it rather than
                # sleeping a fixed interval and hoping.
                try:
                    page.wait_for_selector(
                        'textarea[placeholder="Search homes"]', timeout=15_000
                    )
                except Exception:
                    _record_diagnostic(
                        FEDERA_HOMEPAGE,
                        "Federa search box never rendered within 15s "
                        "(textarea[placeholder='Search homes'] not found) - the "
                        "site layout may have changed, or the page was served a "
                        "different variant.",
                    )
                    return None

                # Must be the VISIBLE textarea, not `.first` - see bug (2).
                search_box = page.locator(
                    'textarea[placeholder="Search homes"]:visible'
                ).first
                if search_box.count() == 0:
                    _record_diagnostic(
                        FEDERA_HOMEPAGE,
                        "Federa search box exists but no visible instance found.",
                    )
                    return None

                search_box.click()
                search_box.fill(search_term)

                # Confirm the text landed before trusting any dropdown - an
                # empty query yields unrelated default suggestions, which is
                # exactly how the Redfin resolver ended up on a Chicago condo
                # for a Tampa address.
                try:
                    typed = (search_box.input_value() or "").strip()
                except Exception:
                    typed = ""
                if not typed:
                    _record_diagnostic(
                        FEDERA_HOMEPAGE,
                        f"Federa search box did not accept the query {search_term!r} "
                        f"(box is empty after fill) - refusing to select a "
                        f"suggestion, since an empty query returns unrelated "
                        f"default results.",
                    )
                    return None

                page.wait_for_timeout(3000)

                # Live DOM structure (verified 2026-07-21):
                #   div.py-2 > ul.divide-y.divide-muted > li > button > span
                #
                # The class filter is REQUIRED, not cosmetic. A bare
                # "ul li button" selector also matches Federa's mobile nav
                # bar (ul.flex.items-stretch.justify-around), which yields
                # the literal items ["Explore", "Assistant", "Menu"] - those
                # would then be fed in as address suggestions. Confirmed
                # live: with an empty search box, "ul li button" returns
                # exactly those three nav entries and nothing else.
                options = page.locator("ul.divide-y li button")
                count = options.count()
                if count == 0:
                    _record_diagnostic(
                        FEDERA_HOMEPAGE,
                        f"No Federa suggestions appeared for {search_term!r} - "
                        f"most likely Federa simply has no listing for this "
                        f"address (expected for many county-courthouse sales).",
                    )
                    return None

                candidates = []
                for i in range(min(count, 10)):
                    try:
                        candidates.append(
                            {"index": i, "text": options.nth(i).inner_text().strip()}
                        )
                    except Exception:
                        continue

                chosen = _pick_matching_suggestion(candidates, search_term)
                if not chosen:
                    _record_diagnostic(
                        FEDERA_HOMEPAGE,
                        f"Federa returned {len(candidates)} suggestion(s) for "
                        f"{search_term!r} but none unambiguously matched "
                        f"(saw: {[c['text'][:60] for c in candidates[:4]]}) - "
                        f"refusing to link to a possibly-wrong property.",
                    )
                    return None

                options.nth(chosen["index"]).click()
                page.wait_for_timeout(4000)
                url = page.url
            finally:
                browser.close()
    except Exception as exc:
        _record_diagnostic(FEDERA_HOMEPAGE, f"{type(exc).__name__}: {exc}")
        return None

    if url and "/property/" in url:
        return url

    _record_diagnostic(
        FEDERA_HOMEPAGE,
        f"Federa search for {search_term!r} did not land on a property page "
        f"(ended at {url!r}).",
    )
    return None
