"""
crime_scraper.py - zip-code crime grade lookup from crimegrade.org
(Phase C.1, 2026-07-13). Replaces the previously-stubbed FBI Crime Data API
approach in scoring.py (get_crime_rate), which required an API key that was
never provisioned and, even with one, needed a ZIP -> ORI mapping step that
was never implemented (see scoring.py's docstring). crimegrade.org publishes
a per-zip "Overall Crime Grade" (A+ through F) with no key/login required.

REAL VERIFICATION LOG (2026-07-13): confirmed live and reachable from this
dev sandbox via a plain GET (no JS rendering needed - unlike RealAuction/
Zillow/Redfin, this is server-rendered HTML). Fetched
https://crimegrade.org/violent-crime-33647/ directly and confirmed the real
page contains a summary table:
    Violent Crime Grade | A
    Property Crime Grade | A
    Other Crime Grade | A
preceded by a large "A+" "Overall Crime Grade(tm)" figure. Parsing below is
regex/text-proximity based (same technique as
estimate_common.extract_dollar_amount_near_label) rather than CSS-selector
based, since this was inspected via extracted page text/markdown rather
than raw DOM class names - more resilient to a markup refresh that doesn't
change the actual wording.

Uses plain `requests` (not Playwright) since the page is confirmed
server-rendered - faster and lower-overhead than a headless browser for a
site that doesn't need one.

Never fabricates a grade - returns None (caller falls back to "unknown /
verify manually") if the page can't be loaded or no grade is found.
"""
import logging
import re
from typing import Any, Dict, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("scrapers.crime")

CRIME_GRADE_URL_TEMPLATE = "https://crimegrade.org/violent-crime-{zip_code}/"
TIMEOUT_SECONDS = 15
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# A standalone grade token (A+, A, A-, B+, ... F), bounded by whitespace/
# punctuation on both sides so this doesn't accidentally match a stray
# capital letter inside an unrelated word.
_GRADE_TOKEN = re.compile(r"(?<![A-Za-z])([ABCDF][+-]?)(?![A-Za-z])")

# crimegrade.org's live page layout (confirmed 2026-07-13) puts the big
# "Overall Crime Grade" figure BEFORE its label ("A+\n\n[Overall Crime
# Grade(tm)]"), while the Violent/Property/Other rows put the grade AFTER
# their label in a table cell. Rather than assume one fixed direction
# (which broke the first version of this scraper - "overall" extraction
# came up empty because it only looked *after* the label), search a window
# of text on BOTH sides of each label for the nearest standalone grade
# token, which is resilient to either layout.
FIELD_LABELS = {
    "overall": "Overall Crime Grade",
    "violent": "Violent Crime Grade",
    "property": "Property Crime Grade",
    "other": "Other Crime Grade",
}
WINDOW_CHARS = 80


def _find_grade_near_label(text: str, label: str) -> Optional[str]:
    idx = text.lower().find(label.lower())
    if idx == -1:
        return None
    start = max(0, idx - WINDOW_CHARS)
    end = min(len(text), idx + len(label) + WINDOW_CHARS)
    window = text[start:end]
    # Prefer the closest match to the label if there are multiple grade-like
    # tokens in the window (e.g. neighboring rows' grades bleeding into the
    # window) - scan outward from the label's position within `window`.
    label_pos_in_window = idx - start
    best = None
    best_distance = None
    for match in _GRADE_TOKEN.finditer(window):
        distance = min(
            abs(match.start() - (label_pos_in_window + len(label))),
            abs(match.end() - label_pos_in_window),
        )
        if best is None or distance < best_distance:
            best = match.group(1)
            best_distance = distance
    return best.upper() if best else None


def get_crime_grade(zip_code: str) -> Optional[Dict[str, Any]]:
    """
    Returns a dict like:
      {"overall": "A+", "violent": "A", "property": "A", "other": "A",
       "source_url": "https://crimegrade.org/violent-crime-33647/"}
    (any of overall/violent/property/other may be absent if not found) or
    None if the zip can't be looked up at all (page unreachable, or no
    recognizable grade found anywhere on the page - never fabricated).
    """
    if not zip_code or not zip_code.strip():
        return None
    zip_code = zip_code.strip()
    url = CRIME_GRADE_URL_TEMPLATE.format(zip_code=zip_code)

    try:
        resp = requests.get(
            url,
            timeout=TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
        )
        if resp.status_code != 200:
            logger.info("crimegrade.org returned HTTP %d for zip %r", resp.status_code, zip_code)
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        text = soup.get_text("\n")
    except Exception as exc:
        logger.warning("crimegrade.org request failed for zip %r: %s", zip_code, exc)
        return None

    grades: Dict[str, str] = {}
    for key, label in FIELD_LABELS.items():
        grade = _find_grade_near_label(text, label)
        if grade:
            grades[key] = grade

    if not grades:
        logger.info("No recognizable crime grade found on %s", url)
        return None

    grades["source_url"] = url
    return grades
