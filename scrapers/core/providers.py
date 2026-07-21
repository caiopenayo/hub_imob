from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any

from .http import SharedScraperHTTPClient
from .types import ListingPage, PropertyCandidate, PropertyDetail, ScrapeRequest


@dataclass(frozen=True)
class ProviderCapabilities:
    supports_sale: bool = True
    supports_city_scope: bool = True
    supports_neighborhood_scope: bool = False
    supports_detail: bool = True
    supports_full_reconciliation: bool = True

    def as_dict(self) -> dict[str, bool]:
        return asdict(self)


class RealEstateProvider(ABC):
    source_key: str
    source_name: str
    base_url: str
    default_search_scope: dict[str, Any] = {}
    enabled: bool = True
    uses_offers: bool = False
    headers: dict[str, str] = {}
    capabilities: ProviderCapabilities = ProviderCapabilities()

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

    def build_listing_url_request(self, url: str) -> ScrapeRequest:
        return ScrapeRequest(url=url, headers=self.headers)

    async def fetch_listing_url(self, client: SharedScraperHTTPClient, url: str) -> str:
        return await client.fetch_text(self.build_listing_url_request(url))

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

    def supports_scope(self, scope: dict[str, Any]) -> bool:
        purpose = str(scope.get("purpose") or "sale").strip().lower()
        if purpose not in {"sale", "venda"}:
            return False
        scope_type = str(scope.get("scope_type") or "full_city")
        if scope_type == "priority_neighborhoods":
            return self.capabilities.supports_neighborhood_scope
        if scope_type == "full_city":
            return self.capabilities.supports_city_scope
        return False

    def search_scope_for_sale_scope(self, scope: dict[str, Any]) -> dict[str, Any]:
        return dict(scope)
