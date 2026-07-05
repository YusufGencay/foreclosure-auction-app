"""
Title search provider abstraction.

Real title/lien searches typically require a commercial title/lien data API
or a licensed title abstraction service (a category of vendor, not named
here so no specific vendor secret gets hardcoded). Configure
TITLE_SEARCH_PROVIDER + TITLE_SEARCH_API_KEY in backend/.env when such a
provider is available; until then StubTitleSearchProvider is used and
always reports that it is not implemented.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Protocol

from pydantic import BaseModel

from backend.config import settings


class TitleSearchResult(BaseModel):
    liens_found: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None


class TitleSearchProvider(Protocol):
    def search(self, address: str, parcel_id: Optional[str] = None) -> TitleSearchResult:
        ...


class BaseTitleSearchProvider(ABC):
    @abstractmethod
    def search(self, address: str, parcel_id: Optional[str] = None) -> TitleSearchResult:
        raise NotImplementedError


class StubTitleSearchProvider(BaseTitleSearchProvider):
    """Default provider when no real TITLE_SEARCH_PROVIDER is configured."""

    def search(self, address: str, parcel_id: Optional[str] = None) -> TitleSearchResult:
        return TitleSearchResult(
            liens_found=None,
            error="not implemented — configure TITLE_SEARCH_PROVIDER and TITLE_SEARCH_API_KEY in .env",
            raw_response=None,
        )


def get_title_search_provider() -> BaseTitleSearchProvider:
    """
    Factory. In the future, branch on settings.TITLE_SEARCH_PROVIDER to
    return a real implementation (e.g. a commercial title/lien data API
    client) once TITLE_SEARCH_API_KEY is configured. Never hardcode a
    vendor secret here.
    """
    if settings.TITLE_SEARCH_PROVIDER and settings.TITLE_SEARCH_API_KEY:
        # Placeholder seam for a real provider integration.
        pass
    return StubTitleSearchProvider()
