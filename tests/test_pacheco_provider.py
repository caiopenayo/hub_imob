import asyncio
from decimal import Decimal
from pathlib import Path

import httpx

from scrapers.core.engine import SyncEngine
from scrapers.core.http import SharedScraperHTTPClient
from scrapers.core.sale_scope import SaleScrapeScope
from scrapers.core.settings import ScraperSettings
from scrapers.core.types import PropertyCandidate, PropertyOfferCandidate
from scrapers.sources.pacheco import DetailIdentityMismatch, UnexpectedListingStructure, provider

FIXTURES = Path(__file__).parent / "fixtures" / "pacheco"


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


def sale_page_1():
    return provider.parse_listing_page(read_fixture("pacheco_listing.html"), 1, {"purpose": "sale"})


def sale_page_2():
    return provider.parse_listing_page(read_fixture("pacheco_listing_page2.html"), 2, {"purpose": "sale"})


def rent_page_1():
    return provider.parse_listing_page(read_fixture("pacheco_rent_listing.html"), 1, {"purpose": "rent"})


def by_id(page, external_id: str):
    return next(candidate for candidate in page.candidates if candidate.external_id == external_id)


def detail_candidate(external_id: str, purpose: str, price: Decimal | None = None) -> PropertyCandidate:
    return PropertyCandidate(
        source_key="pacheco",
        external_id=external_id,
        source_url=f"https://pacheco.com.br/imoveis/{external_id.lower()}/",
        property_type="Casa" if external_id.startswith("Z-") else "Loja",
        transaction_type=purpose,
        price=price,
        offers=[PropertyOfferCandidate(purpose=purpose, price=price, currency="BRL")],
        raw_data={"search_scope": {"purpose": purpose}},
    )


def minimal_card(
    *,
    reference_text: str = "Casa / x9-123",
    href: str = "/imoveis/x9-123/",
    form_id: str = "form-123",
    action_id: str = "123",
    price: str | None = "R$ 1.200.000,00",
    image_url: str | None = "https://cdn.example.com/foto.jpg",
    attrs: str = "<div class=\"infos__item\"><p>70 m²</p></div>",
) -> str:
    reference_html = f"<div class=\"visitar\"><p>{reference_text}</p></div>" if reference_text else ""
    price_html = f"<p class=\"valor\">{price}</p>" if price else ""
    image_html = f"<a href=\"{image_url}\"><img src=\"{image_url}\" /></a>" if image_url else ""
    return f"""
    <form class="imovel item" id="{form_id}" action="https://pacheco.com.br/visitar?action=add&imovel_id={action_id}&status=Vender">
      <div class="box-img">{image_html}</div>
      <div class="box-txt">
        <div class="title"><h3>R TESTE - PINHEIROS</h3></div>
        <div class="infos">{attrs}</div>
        {price_html}
        <a class="box-txt__button" href="{href}">Detalhes</a>
      </div>
      {reference_html}
    </form>
    """


def minimal_detail(external_id: str = "V1-51824", purpose: str = "sale") -> str:
    value_label = "Aluguel:" if purpose == "rent" else "Valor:"
    path_id = external_id.lower()
    return f"""
    <html>
      <head>
        <link rel="canonical" href="https://pacheco.com.br/imoveis/{path_id}/" />
        <meta property="og:image" content="https://cdn.example.com/{path_id}.jpg" />
      </head>
      <body class="postid-321">
        <div class="wrapper-single">
          <div class="hero-carousel">
            <div class="owl-single-imovel">
              <a href="https://cdn.example.com/{path_id}.jpg"><img src="https://cdn.example.com/{path_id}.jpg" /></a>
            </div>
          </div>
          <div class="content">
            <div class="wrapper-dados">
              <div class="infos-imovel">
                <p>Casa - {external_id} / PI0001</p>
                <h1>R TESTE</h1>
                <h2>PINHEIROS</h2>
              </div>
              <div class="wrapper-caracteristicas-imovel">
                <div class="caracteristicas-imovel">
                  <p>Dormitórios: 2</p>
                  <p>Área útil: 70m²</p>
                  <p>ar condicionado</p>
                </div>
              </div>
              <div class="wrapper-descricao-imovel">
                <p>Descrição do Imóvel</p>
                <p>Texto principal.</p>
              </div>
            </div>
          </div>
          <div class="container-valores"><div class="wrapper-valores"><div class="valores">
            <div><p class="bold">{value_label}</p><p class="bold">R$ 1.200.000,00</p></div>
          </div></div></div>
        </div>
      </body>
    </html>
    """


def test_build_search_requests_and_registry():
    assert provider.build_search_request(1, {"purpose": "sale"}).url == "https://pacheco.com.br/comprar/"
    assert provider.build_search_request(2, {"purpose": "sale"}).url == "https://pacheco.com.br/comprar/page/2/"
    assert provider.build_search_request(1, {"purpose": "rent"}).url == "https://pacheco.com.br/alugar/"
    assert provider.build_search_request(3, {"purpose": "rent"}).url == "https://pacheco.com.br/alugar/page/3/"

    from scrapers.core.registry import load_provider, registered_provider_keys

    assert "pacheco" in registered_provider_keys()
    assert load_provider("pacheco").source_key == "pacheco"


def test_priority_pinheiros_request_uses_query_filters():
    scope = provider.search_scope_for_sale_scope(SaleScrapeScope.priority_neighborhoods().as_dict())
    first = provider.build_search_request(1, scope)
    second = provider.build_search_request(2, scope)
    query = "cidades=72&valor-min=&valor-max=&metragem-min=&metragem-max=&referencia=&bairro[]=138&order="

    assert provider.supports_scope(SaleScrapeScope.priority_neighborhoods().as_dict()) is True
    assert first.url == f"https://pacheco.com.br/comprar/?{query}"
    assert second.url == f"https://pacheco.com.br/comprar/page/2/?{query}"


def test_priority_neighborhood_ids_are_mapped_for_all_confirmed_neighborhoods():
    expected_ids = {
        "pinheiros": "138",
        "vila-madalena": "119",
        "perdizes": "137",
        "pompeia": "123",
        "sumare": "132",
        "butanta": "139",
    }

    for slug, term_id in expected_ids.items():
        request = provider.build_search_request(1, {"purpose": "sale", "neighborhood_slug": slug})
        assert f"bairro[]={term_id}" in request.url


def test_sale_listing_fixtures_parse_ids_totals_and_pagination():
    page1 = sale_page_1()
    page2 = sale_page_2()
    ids1 = {candidate.external_id for candidate in page1.candidates}
    ids2 = {candidate.external_id for candidate in page2.candidates}

    assert page1.raw_cards_count == 16
    assert page2.raw_cards_count == 16
    assert len(page1.candidates) == 16
    assert len(page2.candidates) == 16
    assert len(ids1) == 16
    assert len(ids2) == 16
    assert ids1.isdisjoint(ids2)
    assert "V1-51824" in ids1
    assert "Z-100174" in ids1
    assert "Z-101263" in ids2
    assert page1.reported_total == 14615
    assert page1.next_url == "https://pacheco.com.br/comprar/page/2/"
    assert page2.next_url == "https://pacheco.com.br/comprar/page/3/"


def test_sale_listing_candidate_fields_and_sparse_cards():
    page1 = sale_page_1()
    page2 = sale_page_2()
    house = by_id(page1, "V1-51824")
    land = by_id(page1, "Z-100733")
    room = by_id(page2, "Z-101305")

    assert house.source_url == "https://pacheco.com.br/imoveis/v1-51824/"
    assert house.property_type == "Casa"
    assert house.title == "Casa em Vila Madalena"
    assert house.address_line == "R Juatuba"
    assert house.neighborhood == "Vila Madalena"
    assert house.price == Decimal("950000.00")
    assert house.area_m2 == Decimal("90.00")
    assert house.bedrooms == 2
    assert house.bathrooms == 1
    assert house.parking_spaces is None
    assert house.offers[0].purpose == "sale"
    assert house.main_image_url.endswith("PI5454012.jpg")
    assert house.raw_data["wordpress_post_id"] == "64395"
    assert house.raw_data["upstream_reference"] == "PI5454"

    assert land.property_type == "Terreno"
    assert land.area_m2 is None
    assert land.bedrooms is None
    assert land.bathrooms is None
    assert land.parking_spaces is None

    assert room.property_type == "Sala"
    assert room.area_m2 == Decimal("66.00")
    assert room.bedrooms is None
    assert room.bathrooms == 1
    assert room.parking_spaces == 1
    assert room.raw_data["upstream_platform"] == "vista"
    assert room.raw_data["upstream_numeric_id"] == "101305"


def test_rent_listing_l1_fields_images_and_offer():
    candidate = by_id(rent_page_1(), "L1-50943")

    assert candidate.property_type == "Loja"
    assert candidate.address_line == "R Aspicuelta"
    assert candidate.neighborhood == "Vila Madalena"
    assert candidate.area_m2 == Decimal("80.00")
    assert candidate.bedrooms is None
    assert candidate.bathrooms == 2
    assert candidate.parking_spaces == 1
    assert candidate.price == Decimal("10000.00")
    assert candidate.offers[0].purpose == "rent"
    assert candidate.raw_data["commercial_rooms"] == 4
    assert candidate.raw_data["wordpress_post_id"] == "98213"
    assert candidate.raw_data["upstream_reference"] == "PI4126"
    assert len(candidate.raw_data["listing_image_urls"]) == 8
    assert all("youtube" not in image.lower() for image in candidate.raw_data["listing_image_urls"])


def test_listing_edge_cases_normalize_fallbacks_and_reject_bad_cards():
    html = f"""
    <html><body><div class="wrapper-imoveis" id="sticky">
      {minimal_card(reference_text="Casa / x9-123", href="/imoveis/x9-123/", image_url=None)}
      {minimal_card(reference_text="", href="/imoveis/a2-456/", form_id="form-456", action_id="456")}
      {minimal_card(reference_text="Casa / Z-111", href="/imoveis/z-222/", form_id="form-111", action_id="111")}
      {minimal_card(reference_text="Casa / X9-123", href="/imoveis/x9-123/", form_id="form-789", action_id="789")}
      {minimal_card(reference_text="Casa / B7-777", href="", form_id="form-777", action_id="777")}
    </div><a class="next page-numbers" href="/comprar/page/2/"></a></body></html>
    """

    page = provider.parse_listing_page(html, 1, {"purpose": "sale"})

    assert page.next_url == "https://pacheco.com.br/comprar/page/2/"
    assert page.raw_cards_count == 5
    assert page.invalid_cards_count == 3
    assert [candidate.external_id for candidate in page.candidates] == ["X9-123", "A2-456"]
    assert page.candidates[0].main_image_url is None
    assert page.candidates[1].property_type is None


def test_listing_reported_total_without_cards_is_unexpected():
    html = '<html><body><div class="wrapper-imoveis" id="sticky"></div><p>954 Imóveis encontrados</p></body></html>'
    try:
        provider.parse_listing_page(html, 1, {"purpose": "rent"})
    except UnexpectedListingStructure as exc:
        assert "reported results" in str(exc)
    else:
        raise AssertionError("UnexpectedListingStructure was not raised")


def test_sale_detail_fixture_extracts_main_property_only():
    detail = provider.parse_property_detail(
        read_fixture("pacheco_detail.html"),
        detail_candidate("Z-268289", "sale", Decimal("2800000.00")),
    )

    assert detail.external_id == "Z-268289"
    assert detail.canonical_url == "https://pacheco.com.br/imoveis/z-268289/"
    assert detail.property_type == "Casa"
    assert detail.address_line == "R Hermes Fontes"
    assert detail.neighborhood == "Vila Madalena"
    assert detail.raw_data["city"] == "São Paulo"
    assert detail.bedrooms == 3
    assert detail.suites == 1
    assert detail.bathrooms == 4
    assert detail.raw_data["commercial_rooms"] == 2
    assert detail.parking_spaces == 2
    assert detail.area_m2 == Decimal("210.00")
    assert detail.raw_data["raw_construction_year"] == "93"
    assert detail.raw_data["construction_year"] is None
    assert detail.price == Decimal("2800000.00")
    assert detail.property_tax == Decimal("2028.00")
    assert detail.description
    assert detail.raw_data["neighborhood_description"]
    assert len(detail.image_urls) == 19
    assert detail.main_image_url == detail.image_urls[0]
    assert detail.raw_data["wordpress_post_id"] == "81572"
    assert detail.raw_data["upstream_platform"] == "vista"
    assert detail.raw_data["upstream_numeric_id"] == "268289"
    assert "Nome:" not in str(detail.raw_data)


def test_rent_detail_fixture_extracts_monthly_values_and_features():
    candidate = by_id(rent_page_1(), "L1-50943")
    detail = provider.parse_property_detail(read_fixture("pacheco_rent_detail.html"), candidate)

    assert detail.external_id == "L1-50943"
    assert detail.canonical_url == "https://pacheco.com.br/imoveis/l1-50943/"
    assert detail.property_type == "Loja"
    assert detail.address_line == "R Aspicuelta"
    assert detail.neighborhood == "Vila Madalena"
    assert detail.raw_data["city"] == "São Paulo"
    assert detail.bathrooms == 2
    assert detail.raw_data["commercial_rooms"] == 4
    assert detail.parking_spaces == 1
    assert detail.raw_data["construction_year"] == 1963
    assert detail.area_m2 == Decimal("80.00")
    assert "Ar condicionado" in detail.property_features
    assert "Copa" in detail.property_features
    assert "Lavabo" in detail.property_features
    assert detail.price == Decimal("10000.00")
    assert detail.property_tax == Decimal("467.15")
    assert detail.raw_data["property_tax_period"] == "monthly"
    assert detail.raw_data["advertised_monthly_total"] == "10467.15"
    assert detail.condominium_fee is None
    assert len(detail.image_urls) == 8
    assert detail.raw_data["upstream_reference"] == "PI4126"
    assert "DOCUMENTOS NECESSÁRIOS" not in str(detail.raw_data)


def test_detail_identity_mismatch_is_rejected():
    html = read_fixture("pacheco_detail.html").replace("Casa                    - Z-268289 /", "Casa - Z-999999 /", 1)
    try:
        provider.parse_property_detail(html, detail_candidate("Z-268289", "sale"))
    except DetailIdentityMismatch as exc:
        assert "expected Z-268289" in str(exc)
    else:
        raise AssertionError("DetailIdentityMismatch was not raised")


def test_detail_missing_optional_sections_uses_og_image_fallback():
    html = """
    <html><head>
      <link rel="canonical" href="https://pacheco.com.br/imoveis/q2-10/" />
      <meta property="og:image" content="https://cdn.example.com/q2-10.jpg" />
    </head><body class="postid-10">
      <div class="wrapper-single"><div class="content"><div class="wrapper-dados">
        <div class="infos-imovel"><p>Studio - Q2-10 /</p><h1>R TESTE</h1><h2>CENTRO</h2></div>
      </div></div></div>
    </body></html>
    """

    detail = provider.parse_property_detail(
        html,
        PropertyCandidate(
            source_key="pacheco",
            external_id="Q2-10",
            source_url="https://pacheco.com.br/imoveis/q2-10/",
        ),
    )

    assert detail.external_id == "Q2-10"
    assert detail.description is None
    assert detail.property_features == []
    assert detail.image_urls == ["https://cdn.example.com/q2-10.jpg"]
    assert detail.main_image_url == "https://cdn.example.com/q2-10.jpg"


def test_engine_dry_run_follows_next_url_and_fetches_detail():
    async def run():
        def handler(request):
            path = request.url.path
            if path == "/comprar/page/2/":
                return httpx.Response(200, text=read_fixture("pacheco_listing_page2.html"), request=request)
            if path == "/imoveis/v1-51824/":
                return httpx.Response(200, text=minimal_detail("V1-51824"), request=request)
            return httpx.Response(200, text=read_fixture("pacheco_listing.html"), request=request)

        async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        http_client = SharedScraperHTTPClient(settings(), client=async_client)
        try:
            return await SyncEngine(provider, settings(), http_client=http_client).run(
                mode="delta",
                search_scope={"purpose": "sale"},
                dry_run=True,
                max_pages=2,
                max_details=1,
            )
        finally:
            await async_client.aclose()

    stats = asyncio.run(run())

    assert stats.pages_fetched == 2
    assert stats.listings_seen == 32
    assert stats.detail_pages_fetched == 1
    assert stats.stopped_reason == "max_pages"
    assert stats.samples[0]["external_id"] == "V1-51824"
    assert stats.samples[0]["detail"]["external_id"] == "V1-51824"
