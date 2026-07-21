import asyncio
import json
from decimal import Decimal
from pathlib import Path

import httpx

from scrapers.core.engine import SyncEngine
from scrapers.core.http import SharedScraperHTTPClient
from scrapers.core.sale_scope import SaleScrapeScope
from scrapers.core.settings import ScraperSettings
from scrapers.sources.zimoveis import provider

FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def settings(**overrides):
    values = {
        "timeout_seconds": 5,
        "max_retries": 1,
        "concurrency_per_source": 1,
        "request_delay_min_ms": 0,
        "request_delay_max_ms": 0,
        "delta_stale_pages": 1,
    }
    values.update(overrides)
    return ScraperSettings(**values)


def candidate_by_id(candidates, external_id):
    return next(candidate for candidate in candidates if candidate.external_id == external_id)


def test_listing_parser_extracts_cards_and_tolerates_incomplete_card():
    listing = provider.parse_listing_page(read_fixture("zimoveis_listing_page1.html"), page=1)

    assert [candidate.external_id for candidate in listing.candidates].count("261159") == 2
    assert "999999" not in [candidate.external_id for candidate in listing.candidates]

    first = candidate_by_id(listing.candidates, "261159")
    assert first.source_key == "zimoveis"
    assert first.source_url == (
        "https://www.zimoveis.com.br/imovel/apartamento/padrao/perdizes/sao-paulo/rua-jose-donatelli/261159"
    )
    assert first.main_image_url == "https://www.zimoveis.com.br/fotos/261159-thumb.jpg?ts=123"
    assert first.neighborhood == "Perdizes"
    assert first.property_type == "Apartamento"
    assert first.property_subtype == "Padrão"
    assert first.city == "Sao Paulo"
    assert first.state == "SP"
    assert first.price == Decimal("6000000.00")
    assert first.address_line == "Rua José Donatelli"
    assert first.area_m2 == Decimal("183.00")
    assert first.bedrooms == 4
    assert first.suites == 2
    assert first.bathrooms == 2
    assert first.parking_spaces == 3
    assert first.tags == ["Vídeo", "Permuta", "360º"]
    assert first.raw_data["listing_hash"]


def test_listing_parser_handles_missing_suite_and_tags():
    listing = provider.parse_listing_page(read_fixture("zimoveis_listing_page1.html"), page=1)
    second = candidate_by_id(listing.candidates, "170805")

    assert second.property_type == "Cobertura Duplex"
    assert second.suites is None
    assert second.bathrooms is None
    assert second.tags == []
    assert second.main_image_url == "https://www.zimoveis.com.br/fotos/170805-thumb.jpg"


def test_newscroll_request_uses_ajax_headers_and_page_param():
    first = provider.build_search_request(1, {"q": "Sao Paulo"})
    second = provider.build_search_request(2, {"q": "Sao Paulo"})

    assert first.url == "https://www.zimoveis.com.br/buscar-imoveis?q=Sao+Paulo"
    assert "newscroll" not in first.url
    assert second.url == "https://www.zimoveis.com.br/buscar-imoveis?q=Sao+Paulo&newscroll=1&page=2"
    assert second.headers["X-Requested-With"] == "XMLHttpRequest"
    assert second.headers["Referer"] == "https://www.zimoveis.com.br/buscar-imoveis?q=Sao+Paulo"


def test_priority_pinheiros_request_uses_bairros_param():
    scope = provider.search_scope_for_sale_scope(SaleScrapeScope.priority_neighborhoods().as_dict())
    first = provider.build_search_request(1, scope)
    second = provider.build_search_request(2, scope)

    assert provider.supports_scope(SaleScrapeScope.priority_neighborhoods().as_dict()) is True
    assert first.url == "https://www.zimoveis.com.br/buscar-imoveis?bairros=pinheiros"
    assert second.url == "https://www.zimoveis.com.br/buscar-imoveis?bairros=pinheiros&newscroll=1&page=2"
    assert second.headers["Referer"] == "https://www.zimoveis.com.br/buscar-imoveis?bairros=pinheiros"


def test_newscroll_parser_accepts_json_html_wrapper():
    wrapped = json.dumps({"html": read_fixture("zimoveis_listing_page2.html")})
    listing = provider.parse_listing_page(wrapped, page=2)

    assert listing.raw_cards_count == 1
    assert listing.candidates[0].external_id == "300001"


def test_detail_parser_extracts_gallery_description_costs_features_location_and_video():
    candidate = candidate_by_id(provider.parse_listing_page(read_fixture("zimoveis_listing_page1.html"), 1).candidates, "170805")
    detail = provider.parse_property_detail(read_fixture("zimoveis_detail_full.html"), candidate)

    assert detail.external_id == "170805"
    assert detail.title == "Apartamento à Venda em Perdizes com 4 Dormitórios"
    assert detail.canonical_url.endswith("/rua-aimbere/170805")
    assert detail.price == Decimal("3100000.00")
    assert detail.price_per_m2 == Decimal("16929.00")
    assert detail.condominium_fee == Decimal("2100.00")
    assert detail.property_tax == Decimal("980.00")
    assert detail.neighborhood == "Perdizes"
    assert detail.address_line == "Rua Aimberê"
    assert detail.bedrooms == 4
    assert detail.suites == 2
    assert detail.bathrooms == 3
    assert detail.parking_spaces == 3
    assert detail.area_m2 == Decimal("183.00")
    assert detail.description == "Apartamento amplo e iluminado.\n\nPlanta bem distribuída com varanda."
    assert detail.property_features == ["Varanda", "Lavabo", "Ar-condicionado"]
    assert detail.condominium_description == "Condomínio com lazer completo."
    assert detail.condominium_features == ["Piscina", "Academia"]
    assert detail.nearby_points == [
        {
            "type": "Metrô",
            "name": "Estação Vila Madalena",
            "distance_text": "1,2 km",
            "distance_meters": 1200,
        },
        {"type": "Escola", "name": "Colégio Exemplo", "distance_text": "350 m", "distance_meters": 350},
    ]
    assert detail.image_urls == [
        "https://www.zimoveis.com.br/fotos/170805-1.jpg?ts=1",
        "https://www.zimoveis.com.br/fotos/170805-2.jpg?ts=2",
    ]
    assert detail.main_image_url == "https://www.zimoveis.com.br/fotos/170805-1.jpg?ts=1"
    assert detail.video_urls == ["https://www.youtube.com/embed/video123"]
    assert detail.latitude == Decimal("-23.5404996")
    assert detail.longitude == Decimal("-46.6858253")
    assert detail.raw_data["location_precision"] == "approximate"
    assert "SHOULD_NOT_BE_STORED" not in str(detail.raw_data)


def test_detail_parser_handles_missing_condominium_and_iptu_with_og_image():
    candidate = candidate_by_id(provider.parse_listing_page(read_fixture("zimoveis_listing_page2.html"), 2).candidates, "300001")
    detail = provider.parse_property_detail(read_fixture("zimoveis_detail_no_fees.html"), candidate)

    assert detail.external_id == "300001"
    assert detail.condominium_fee is None
    assert detail.property_tax is None
    assert detail.image_urls == ["https://www.zimoveis.com.br/fotos/300001-og.jpg?ts=4"]
    assert detail.main_image_url == "https://www.zimoveis.com.br/fotos/300001-og.jpg?ts=4"


def test_distance_parser_accepts_metros_and_km_text():
    assert provider._distance("818 metros") == ("818 metros", 818)
    assert provider._distance("1,40 km") == ("1,40 km", 1400)


def test_engine_paginates_until_empty_page_and_dedupes_ids():
    async def run():
        def handler(request):
            page = request.url.params.get("page")
            if page == "2":
                return httpx.Response(200, text=read_fixture("zimoveis_listing_page2.html"), request=request)
            if page == "3":
                return httpx.Response(200, text=read_fixture("zimoveis_listing_empty.html"), request=request)
            return httpx.Response(200, text=read_fixture("zimoveis_listing_page1.html"), request=request)

        async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        http_client = SharedScraperHTTPClient(settings(), client=async_client)
        try:
            return await SyncEngine(provider, settings(), http_client=http_client).run(
                mode="delta",
                dry_run=True,
                max_pages=5,
            )
        finally:
            await async_client.aclose()

    stats = asyncio.run(run())
    assert stats.pages_fetched == 3
    assert stats.listings_seen == 3
    assert stats.stopped_reason == "no_cards"
    assert [sample["external_id"] for sample in stats.samples] == ["261159", "170805", "300001"]


def test_engine_stops_on_repeated_page_without_looping():
    async def run():
        def handler(request):
            return httpx.Response(200, text=read_fixture("zimoveis_listing_page1.html"), request=request)

        async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        http_client = SharedScraperHTTPClient(settings(), client=async_client)
        try:
            return await SyncEngine(provider, settings(), http_client=http_client).run(
                mode="delta",
                dry_run=True,
                max_pages=5,
            )
        finally:
            await async_client.aclose()

    stats = asyncio.run(run())
    assert stats.pages_fetched == 2
    assert stats.stopped_reason == "repeated_page"
    assert stats.completed is True


def test_engine_treats_listing_404_after_first_page_as_clean_stop():
    async def run():
        def handler(request):
            if request.url.params.get("page") == "2":
                return httpx.Response(404, request=request)
            return httpx.Response(200, text=read_fixture("zimoveis_listing_page1.html"), request=request)

        async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        http_client = SharedScraperHTTPClient(settings(max_retries=0), client=async_client)
        try:
            return await SyncEngine(provider, settings(max_retries=0), http_client=http_client).run(
                mode="delta",
                dry_run=True,
                max_pages=5,
            )
        finally:
            await async_client.aclose()

    stats = asyncio.run(run())
    assert stats.completed is True
    assert stats.stopped_reason == "http_404"
    assert stats.http_errors == []


def test_engine_marks_listing_429_as_partial(monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("scrapers.core.http.asyncio.sleep", no_sleep)

    async def run():
        def handler(request):
            if request.url.params.get("page") == "2":
                return httpx.Response(429, request=request)
            return httpx.Response(200, text=read_fixture("zimoveis_listing_page1.html"), request=request)

        async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        http_client = SharedScraperHTTPClient(settings(max_retries=1), client=async_client)
        try:
            return await SyncEngine(provider, settings(max_retries=1), http_client=http_client).run(
                mode="delta",
                dry_run=True,
                max_pages=5,
            )
        finally:
            await async_client.aclose()

    stats = asyncio.run(run())
    assert stats.completed is False
    assert stats.stopped_reason == "http_429"
    assert stats.http_errors[0]["status_code"] == 429
