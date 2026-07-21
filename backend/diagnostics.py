"""
diagnostics.py - outbound network reachability probe, run FROM the Railway
production container.

WHY THIS EXISTS (2026-07-21)
----------------------------
The 2026-07-17 session established, with hard evidence, that
html.duckduckgo.com is unreachable from Railway (ConnectTimeout via both
Playwright's request context and the plain `requests` library). Because
every one of the Zillow / Realtor.com / Redfin / Auction.com resolvers
depends on that single DuckDuckGo call (see
estimate_common.resolve_property_url_via_search), all four fail identically.

The conclusion drawn at the time was "we need a paid search API or a paid
proxy". That conclusion does not actually follow from the evidence. What
was proven is narrow: *one specific host* is unreachable. What was never
tested is whether ANY OTHER host is reachable - including:

  (a) other free, no-key, no-JS search endpoints (Mojeek, Brave, Bing,
      Startpage, Ecosia, DuckDuckGo's own `lite.` variant), any one of
      which could be a drop-in replacement for the same
      `site:<domain> <address>` query at zero cost; and
  (b) the destination listing sites themselves (zillow.com, redfin.com,
      realtor.com, federa.com, auction.com) - which matters enormously,
      because if those ARE reachable then the whole search-engine
      middleman can be removed rather than replaced, by driving each
      site's own public search UI with Playwright the way
      federa_scraper.py already does.

Note also that realauction_playwright.py successfully scrapes 14 different
county auction sites from this exact container every single day. So there
is no blanket "outbound network is broken" problem here - something is
reachable. This probe finds out precisely what.

DESIGN NOTES
------------
- Read-only. Issues one plain GET per target and reports what came back.
  No writes, no side effects, no state mutated anywhere in the app.
- Runs targets concurrently with a short per-target timeout so the whole
  sweep returns in seconds rather than minutes (the sequential 30s-timeout
  pattern used elsewhere in this codebase is what makes /enrich take
  several minutes when things are failing).
- Reports the REAL exception type and message per target, never a
  swallowed generic "unavailable" - the same honesty principle the
  2026-07-17 session added to estimate_common via
  get_last_fetch_diagnostic(). A probe that hides why something failed is
  worse than no probe.
- Includes known-good control targets (example.com, and a county
  RealAuction host that provably works in production). If the controls
  fail too, the result means "this probe or the whole container's egress
  is broken", not "these specific sites block us" - without controls the
  output would be uninterpretable.
- Fabricates nothing: an inconclusive result is reported as inconclusive.
"""
import concurrent.futures
import logging
import re
import time
from typing import Optional

logger = logging.getLogger("diagnostics")

PROBE_TIMEOUT_SECONDS = 10
MAX_WORKERS = 8

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# (label, url, category). Categories group the interpretation:
#   control       - known to work; if these fail the whole probe is suspect
#   search        - candidate free replacements for the DuckDuckGo dependency
#   destination   - the listing sites we ultimately need to read
PROBE_TARGETS = [
    ("example.com", "https://example.com/", "control"),
    ("hillsborough realauction", "https://hillsborough.realforeclose.com/", "control"),

    ("duckduckgo html (known bad)", "https://html.duckduckgo.com/html/?q=test", "search"),
    ("duckduckgo lite", "https://lite.duckduckgo.com/lite/?q=test", "search"),
    ("duckduckgo main", "https://duckduckgo.com/?q=test", "search"),
    ("mojeek", "https://www.mojeek.com/search?q=test", "search"),
    ("brave search", "https://search.brave.com/search?q=test", "search"),
    ("bing", "https://www.bing.com/search?q=test", "search"),
    ("startpage", "https://www.startpage.com/sp/search?query=test", "search"),
    ("ecosia", "https://www.ecosia.org/search?q=test", "search"),
    ("searx.be", "https://searx.be/search?q=test", "search"),

    ("zillow", "https://www.zillow.com/", "destination"),
    ("redfin", "https://www.redfin.com/", "destination"),
    ("realtor.com", "https://www.realtor.com/", "destination"),
    ("federa", "https://www.federa.com/", "destination"),
    ("auction.com", "https://www.auction.com/", "destination"),
]

BLOCK_MARKERS = (
    "captcha",
    "are you a robot",
    "access to this page has been denied",
    "unusual traffic",
    "press and hold",
    "verify you are a human",
    "enable javascript and cookies to continue",
)


def _classify(status: Optional[int], text: Optional[str], error: Optional[str]) -> str:
    """Turn a raw probe result into a one-word verdict a human can scan.

    Deliberately conservative: anything ambiguous is reported as such
    rather than being optimistically called reachable."""
    if error:
        low = error.lower()
        if "connecttimeout" in low or "readtimeout" in low or "timeout" in low:
            return "UNREACHABLE (timeout - no response at all)"
        if "nameresolution" in low or "gaierror" in low or "dns" in low:
            return "UNREACHABLE (DNS failure)"
        if "sslerror" in low or "certificate" in low:
            return "UNREACHABLE (TLS failure)"
        return "UNREACHABLE (connection error)"

    if status is None:
        return "INCONCLUSIVE (no status)"

    lowered = (text or "").lower()
    if any(m in lowered for m in BLOCK_MARKERS):
        return f"REACHABLE BUT BOT-BLOCKED (HTTP {status}, challenge page)"

    if status in (401, 403, 429):
        return f"REACHABLE BUT REFUSED (HTTP {status})"
    if status >= 500:
        return f"REACHABLE, SERVER ERROR (HTTP {status})"
    if 200 <= status < 400:
        if not (text or "").strip():
            return f"REACHABLE BUT EMPTY BODY (HTTP {status})"
        return f"OK (HTTP {status})"
    return f"UNEXPECTED (HTTP {status})"


def _probe_one(label: str, url: str, category: str) -> dict:
    started = time.monotonic()
    status = None
    text = None
    error = None

    try:
        import requests
    except ImportError:
        return {
            "target": label, "url": url, "category": category,
            "verdict": "INCONCLUSIVE (requests library not installed)",
            "status": None, "elapsed_seconds": 0.0, "error": "ImportError: requests",
            "body_sample": None,
        }

    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=PROBE_TIMEOUT_SECONDS,
            allow_redirects=True,
        )
        status = response.status_code
        text = response.text
    except Exception as exc:
        # Full type + message, never swallowed - this is the entire point.
        error = f"{type(exc).__name__}: {exc}"

    elapsed = round(time.monotonic() - started, 2)
    sample = None
    if text:
        sample = re.sub(r"\s+", " ", text[:400]).strip()

    return {
        "target": label,
        "url": url,
        "category": category,
        "verdict": _classify(status, text, error),
        "status": status,
        "elapsed_seconds": elapsed,
        "error": error,
        "body_length": len(text) if text is not None else None,
        "body_sample": sample,
    }


def run_connectivity_probe() -> dict:
    """Probe every target concurrently and return a structured report."""
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(_probe_one, *t) for t in PROBE_TARGETS]
        for fut in concurrent.futures.as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as exc:  # a probe itself blowing up is itself data
                results.append({
                    "target": "unknown",
                    "verdict": "INCONCLUSIVE (probe raised)",
                    "error": f"{type(exc).__name__}: {exc}",
                })

    order = {label: i for i, (label, _, _) in enumerate(PROBE_TARGETS)}
    results.sort(key=lambda r: order.get(r.get("target"), 999))

    def _ok(r):
        return str(r.get("verdict", "")).startswith("OK")

    controls_ok = [r for r in results if r.get("category") == "control" and _ok(r)]
    usable_search = [r["target"] for r in results if r.get("category") == "search" and _ok(r)]
    usable_dest = [r["target"] for r in results if r.get("category") == "destination" and _ok(r)]

    if not controls_ok:
        summary = (
            "CONTROLS FAILED - every control target was unreachable, so this "
            "container appears to have no working outbound egress at all (or the "
            "probe itself is broken). Do NOT interpret the other rows as "
            "site-specific blocks."
        )
    else:
        summary = (
            f"Controls OK. Usable free search hosts: "
            f"{usable_search or 'NONE'}. Directly reachable destination sites: "
            f"{usable_dest or 'NONE'}."
        )

    return {
        "probed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "timeout_seconds_per_target": PROBE_TIMEOUT_SECONDS,
        "summary": summary,
        "usable_search_hosts": usable_search,
        "reachable_destination_sites": usable_dest,
        "results": results,
    }
