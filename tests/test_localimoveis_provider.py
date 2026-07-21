import asyncio
from decimal import Decimal
from pathlib import Path

import httpx

from scrapers.core.engine import SyncEngine
from scrapers.core.http import SharedScraperHTTPClient
from scrapers.core.sale_scope import SaleScrapeScope
from scrapers.core.settings import ScraperSettings
from scrapers.sources.localimoveis import DetailIdentityMismatch, provider

FIXTURES = Path(__file__).parent / "fixtures" / "localimoveis"


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


def listing():
    return provider.parse_listing_page(read_fixture("listing_page_1.html"), 1, provider.default_search_scope)


def candidate_by_id(external_id: str):
    return next(candidate for candidate in listing().candidates if candidate.external_id == external_id)


def minimal_card(
    *,
    code: str = "9001",
    url_code: str | None = None,
    image: bool = True,
    price: str | None = "R$ 1.200.000,00",
    parking: str | None = "2 Vagas",
    relative_url: bool = False,
) -> str:
    url_code = url_code or code
    href = f"/imovel/apartamento-a-venda-sao-paulo-pinheiros-52m2-1dormitorio/{url_code}"
    if not relative_url:
        href = f"https://www.localimoveis.com.br{href}"
    photo = (
        "<div class=\"card-foto\" style=\"background-image: url('https://betaimages.lopes.com.br/realestate/REO"
        f"{code}/foto.JPG')\"></div>"
        if image
        else ""
    )
    price_html = f"<h3>Venda</h3><h2>{price}</h2>" if price else "<h3>Venda</h3>"
    parking_html = f"<div class=\"texto\"><label class=\"one\">{parking}</label></div>" if parking else ""
    return f"""
    <div class="card-imovel">
      <a href="{href}">{photo}</a>
      <div class="info"><div class="largura">
        <div class="colunaTipo1"><h2>APARTAMENTO - RESIDENCIAL</h2></div>
        <h2 class="refDireita1"><span>Cod: {code}</span></h2>
        <h3>PINHEIROS</h3>
        <div class="retorno">
          <div class="texto"><label>52,5 m²</label><label>Área útil</label></div>
          <div class="texto"><label class="one">1 Quartos</label></div>
          {parking_html}
        </div>
        <div class="bloco-valores">{price_html}</div>
        <a class="link" href="{href}">Conhecer</a>
      </div></div>
    </div>
    """


def test_listing_parser_extracts_real_fixture_and_next_url():
    page = listing()

    assert page.raw_cards_count == 64
    assert len(page.candidates) == 64
    assert len({candidate.external_id for candidate in page.candidates}) == 64
    assert page.next_url == "https://www.localimoveis.com.br/imoveis/venda/sp/sao-paulo/2"
    assert page.reported_total == 11709


def test_listing_candidate_6485_fields_and_offer():
    candidate = candidate_by_id("6485")

    assert candidate.source_key == "localimoveis"
    assert candidate.external_id == "6485"
    assert candidate.source_url.endswith("/6485")
    assert candidate.property_type == "Apartamento"
    assert candidate.property_subtype == "Residencial"
    assert candidate.neighborhood == "Pinheiros"
    assert candidate.city == "São Paulo"
    assert candidate.state == "SP"
    assert candidate.area_m2 == Decimal("332.00")
    assert candidate.raw_data["usable_area_m2"] == "332.00"
    assert candidate.raw_data["total_area_m2"] == "332.00"
    assert candidate.bedrooms == 4
    assert candidate.parking_spaces == 4
    assert candidate.price == Decimal("8850000.00")
    assert candidate.offers[0].purpose == "sale"
    assert candidate.offers[0].price == Decimal("8850000.00")
    assert candidate.main_image_url.endswith("124455523E83BCD6B300CF7683162FDE.JPG")
    assert candidate.raw_data["reo_reference"] == "REO6485"


def test_listing_commercial_and_multi_offer_cases():
    commercial = candidate_by_id("8273")
    mixed = candidate_by_id("18197")

    assert commercial.property_type == "Prédio Inteiro"
    assert commercial.property_subtype == "Comercial"
    assert commercial.area_m2 == Decimal("850.00")
    assert commercial.raw_data["total_area_m2"] == "1100.00"
    assert commercial.bedrooms is None
    assert commercial.parking_spaces == 17
    assert commercial.price == Decimal("24000000.00")

    assert mixed.property_type == "Salas"
    assert mixed.property_subtype == "Comercial"
    assert [(offer.purpose, offer.price) for offer in mixed.offers] == [
        ("rent", Decimal("20000.00")),
        ("sale", Decimal("4500000.00")),
    ]
    assert mixed.price == Decimal("4500000.00")


def test_background_image_url_variants():
    assert provider.extract_background_image_url("background-image: url('https://x.test/foto.JPG')") == "https://x.test/foto.JPG"
    assert provider.extract_background_image_url('background-image: url("https://x.test/foto.webp")') == "https://x.test/foto.webp"
    assert provider.extract_background_image_url("background-image: url( https://x.test/foto.png )") == "https://x.test/foto.png"
    assert provider.extract_background_image_url("background-image: none") is None


def test_listing_edge_cases_do_not_break_page():
    html = f"""
    <html><head><link rel="next" href="/imoveis/venda/sp/sao-paulo/2"></head><body>
      {minimal_card(code="9001", image=False, price=None, parking=None, relative_url=True)}
      {minimal_card(code="9002", url_code="9999")}
      {minimal_card(code="9001")}
      <div class="card-imovel">malformado</div>
    </body></html>
    """
    page = provider.parse_listing_page(html, 1, provider.default_search_scope)

    assert page.next_url == "https://www.localimoveis.com.br/imoveis/venda/sp/sao-paulo/2"
    assert page.raw_cards_count == 4
    assert page.invalid_cards_count == 2
    assert [candidate.external_id for candidate in page.candidates].count("9001") == 2
    first = page.candidates[0]
    assert first.source_url == "https://www.localimoveis.com.br/imovel/apartamento-a-venda-sao-paulo-pinheiros-52m2-1dormitorio/9001"
    assert first.main_image_url is None
    assert first.price is None
    assert first.parking_spaces is None
    assert first.area_m2 == Decimal("52.50")


def test_detail_6485_extracts_main_property_only():
    detail = provider.parse_property_detail(read_fixture("detail_6485.html"), candidate_by_id("6485"))

    assert detail.external_id == "6485"
    assert detail.canonical_url == "https://www.localimoveis.com.br/imovel/apartamento-a-venda-sao-paulo-pinheiros-332m2-4dormitorios-4vagas/6485"
    assert detail.property_type == "Apartamento"
    assert detail.property_subtype == "Residencial"
    assert detail.neighborhood == "Pinheiros"
    assert detail.raw_data["address"]["city"] == "São Paulo"
    assert detail.raw_data["address"]["state"] == "SP"
    assert detail.price == Decimal("8850000.00")
    assert detail.condominium_fee == Decimal("4500.00")
    assert detail.property_tax == Decimal("1980.00")
    assert detail.area_m2 == Decimal("332.00")
    assert detail.raw_data["usable_area_m2"] == "332.00"
    assert detail.raw_data["total_area_m2"] == "332.00"
    assert detail.bedrooms == 4
    assert detail.suites == 4
    assert detail.bathrooms == 5
    assert detail.parking_spaces == 4
    assert detail.description
    assert len(detail.image_urls) == 34
    assert detail.main_image_url == detail.image_urls[0]
    assert len(detail.property_features) == 8
    assert detail.address_line == "Rua Simão Álvares"
    assert detail.raw_data["address"]["postal_code"] == "05417-020"
    assert detail.raw_data["location_precision"] == "approximate"
    assert detail.latitude is None
    assert detail.longitude is None
    assert "AIza" not in str(detail.raw_data)


def test_detail_missing_optional_sections_and_og_image_fallback():
    html = read_fixture("detail_6485.html")
    html = html.replace('id="conta-com"', 'id="conta-removido"', 1)
    html = html.replace('R$ 4.500,00', 'Sob consulta', 1)
    html = html.replace('R$ 1.980,00', 'Isento', 1)
    html = html.replace('class="slider"', 'class="slider-removido"', 1)
    detail = provider.parse_property_detail(html, candidate_by_id("6485"))

    assert detail.condominium_fee is None
    assert detail.property_tax is None
    assert detail.property_features == []
    assert detail.image_urls
    assert detail.main_image_url.endswith("124455523E83BCD6B300CF7683162FDE.JPG")


def test_detail_identity_mismatch_is_rejected():
    html = read_fixture("detail_6485.html").replace("Cod: 6485", "Cod: 9999", 1)
    try:
        provider.parse_property_detail(html, candidate_by_id("6485"))
    except DetailIdentityMismatch as exc:
        assert "expected 6485" in str(exc)
    else:
        raise AssertionError("DetailIdentityMismatch was not raised")


def test_engine_follows_rel_next_url():
    page2 = f"<html><body>{minimal_card(code='9902')}</body></html>"

    async def run():
        def handler(request):
            if request.url.path.endswith("/sao-paulo/2"):
                return httpx.Response(200, text=page2, request=request)
            return httpx.Response(200, text=read_fixture("listing_page_1.html"), request=request)

        async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        http_client = SharedScraperHTTPClient(settings(), client=async_client)
        try:
            return await SyncEngine(provider, settings(), http_client=http_client).run(
                mode="delta",
                dry_run=True,
                max_pages=2,
            )
        finally:
            await async_client.aclose()

    stats = asyncio.run(run())
    assert stats.pages_fetched == 2
    assert stats.listings_seen == 65
    assert stats.stopped_reason == "max_pages"


def test_registry_loads_provider():
    from scrapers.core.registry import load_provider, registered_provider_keys

    assert "localimoveis" in registered_provider_keys()
    assert load_provider("localimoveis").source_key == "localimoveis"


def test_priority_pinheiros_request_uses_neighborhood_path():
    scope = provider.search_scope_for_sale_scope(SaleScrapeScope.priority_neighborhoods().as_dict())
    first = provider.build_search_request(1, scope)
    second = provider.build_search_request(2, scope)

    assert provider.supports_scope(SaleScrapeScope.priority_neighborhoods().as_dict()) is True
    assert first.url == "https://www.localimoveis.com.br/imoveis/venda/sp/sao-paulo/pinheiros"
    assert second.url == "https://www.localimoveis.com.br/imoveis/venda/sp/sao-paulo/pinheiros/2"
