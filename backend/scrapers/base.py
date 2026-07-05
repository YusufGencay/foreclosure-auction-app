"""
base.py - Abstract base scraper for county auction portals.

Design principles:
- Rate limited: enforces a minimum delay between outbound HTTP requests.
- Retries with backoff via `requests` (max 3 attempts).
- Never fabricates data: if a page can't be parsed (JS-rendered, blocked,
  unexpected structure), the scraper must return success=False with a clear
  error_message rather than inventing records.
- Per-county isolation: any exception raised inside a scraper's `scrape()`
  must be caught at the CALL SITE (see `run_scraper_safely`) so that one
  county's failure never crashes a batch job across all counties.
"""
import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("scrapers")


@dataclass
class ScrapeResult:
    success: bool
    records: List[Dict[str, Any]] = field(default_factory=list)
    error_message: Optional[str] = None


class BaseScraper(ABC):
    """Abstract base class all county/platform scraper adapters extend."""

    # Minimum seconds to wait between outbound HTTP requests to be a polite,
    # non-abusive scraper against these public county portals.
    MIN_DELAY_SECONDS = 2.0
    MAX_RETRIES = 3
    BACKOFF_BASE_SECONDS = 1.5
    TIMEOUT_SECONDS = 15
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(self):
        self._last_request_time: Optional[float] = None

    def _respect_rate_limit(self):
        if self._last_request_time is not None:
            elapsed = time.monotonic() - self._last_request_time
            wait_for = self.MIN_DELAY_SECONDS - elapsed
            if wait_for > 0:
                time.sleep(wait_for)

    def get_with_retry(self, url: str, **kwargs) -> requests.Response:
        """GET a URL with rate limiting + retry/backoff. Raises on final failure."""
        headers = kwargs.pop("headers", {})
        headers.setdefault("User-Agent", self.USER_AGENT)

        last_exc = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            self._respect_rate_limit()
            try:
                self._last_request_time = time.monotonic()
                resp = requests.get(
                    url, headers=headers, timeout=self.TIMEOUT_SECONDS, **kwargs
                )
                return resp
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning(
                    "Request attempt %d/%d to %s failed: %s",
                    attempt, self.MAX_RETRIES, url, exc,
                )
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.BACKOFF_BASE_SECONDS * attempt)
        raise last_exc

    @abstractmethod
    def scrape(self, county_config: Dict[str, Any]) -> ScrapeResult:
        """
        Attempt to scrape a county's auction portal.

        county_config: dict with keys like county, portal_url, platform, etc.
        Returns a ScrapeResult. Must NEVER fabricate records - if scraping is
        blocked or requires JS rendering, return success=False with a clear
        error_message.
        """
        raise NotImplementedError

    @staticmethod
    def log_scrape(db_session, county: str, result: ScrapeResult):
        """Persist a ScrapeResult to the scrape_logs table."""
        from models import ScrapeLog  # local import avoids circular import

        log = ScrapeLog(
            county=county,
            timestamp=datetime.utcnow(),
            success=result.success,
            error_message=result.error_message,
            records_found=len(result.records) if result.records else 0,
        )
        db_session.add(log)
        db_session.commit()
        return log


def run_scraper_safely(scraper: BaseScraper, county_config: Dict[str, Any]) -> ScrapeResult:
    """
    Call site wrapper: guarantees a single county's scraper exception can
    NEVER propagate and crash a batch "scrape all counties" job.
    """
    county_name = county_config.get("county", "UNKNOWN")
    try:
        return scraper.scrape(county_config)
    except Exception as exc:  # noqa: BLE001 - intentional broad catch, see docstring
        logger.exception("Unhandled exception scraping county %s", county_name)
        return ScrapeResult(
            success=False,
            records=[],
            error_message=f"Unhandled scraper exception: {exc}",
        )
