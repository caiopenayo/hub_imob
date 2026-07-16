from __future__ import annotations

from urllib.parse import urlencode

from scrapers.core.providers import RealEstateProvider
from scrapers.core.types import ListingPage, ScrapeRequest


class ZimmermannProvider(RealEstateProvider):
    source_key = "zimmermann"
    source_name = "Zimmermann Imóveis"
    base_url = "https://www.zimoveis.com.br"
    default_search_scope = {"q": "Sao Paulo"}

    def build_search_request(self, page: int, search_scope: dict | None = None) -> ScrapeRequest:
        scope = {**self.default_search_scope, **(search_scope or {})}
        params = {key: value for key, value in scope.items() if value not in (None, "")}
        if page > 1:
            params["pagina"] = page
        query = urlencode(params)
        return ScrapeRequest(url=f"{self.base_url}/buscar-imoveis?{query}")

    def parse_listing_page(self, html: str, page: int, search_scope: dict | None = None) -> ListingPage:
        # Parser intentionally left minimal in this phase. The shared framework can
        # run this provider in dry-run without coupling Zimmermann-specific HTML to
        # the synchronization engine.
        return ListingPage(candidates=[], next_page=None, is_complete=True)


provider = ZimmermannProvider()
