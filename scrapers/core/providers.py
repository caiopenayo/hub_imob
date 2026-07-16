from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .http import SharedScraperHTTPClient
from .types import ListingPage, PropertyCandidate, PropertyDetail, ScrapeRequest


class RealEstateProvider(ABC):
    source_key: str
    source_name: str
    base_url: str
    default_search_scope: dict[str, Any] = {}
    enabled: bool = True
    headers: dict[str, str] = {}

    @abstractmethod
    def build_search_request(self, page: int, search_scope: dict[str, Any] | None = None) -> ScrapeRequest:
        """Build a public listing/search page request."""

    async def fetch_listing_page(
        self,
        client: SharedScraperHTTPClient,
        page: int,
        search_scope: dict[str, Any] | None = None,
    ) -> str:
        return await client.fetch_text(self.build_search_request(page=page, search_scope=search_scope))

    @abstractmethod
    def parse_listing_page(
        self,
        html: str,
        page: int,
        search_scope: dict[str, Any] | None = None,
    ) -> ListingPage:
        """Parse listing HTML into source-specific candidates."""

    def build_detail_request(self, candidate: PropertyCandidate) -> ScrapeRequest:
        return ScrapeRequest(url=candidate.source_url)

    async def fetch_property_detail(
        self,
        client: SharedScraperHTTPClient,
        candidate: PropertyCandidate,
    ) -> str:
        return await client.fetch_text(self.build_detail_request(candidate))

    def parse_property_detail(self, html: str, candidate: PropertyCandidate) -> PropertyDetail:
        return PropertyDetail(external_id=candidate.external_id, raw_data={"detail_parser": "not_implemented"})

    def normalize_listing(self, candidate: PropertyCandidate) -> PropertyCandidate:
        return candidate

    def normalize_detail(self, candidate: PropertyCandidate, detail: PropertyDetail) -> PropertyDetail:
        return detail

