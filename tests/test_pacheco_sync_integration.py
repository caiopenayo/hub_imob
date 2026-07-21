import asyncio
from decimal import Decimal
from pathlib import Path

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.db.models import Base, Property, PropertyEvent, PropertyOffer, PropertyPhoto, Source
from scrapers.core.engine import SyncEngine
from scrapers.core.http import SharedScraperHTTPClient
from scrapers.core.settings import ScraperSettings
from scrapers.sources.pacheco import provider


FIXTURES = Path(__file__).parent / "fixtures" / "pacheco"


class AsyncSessionAdapter:
    def __init__(self, sync_session):
        self.sync_session = sync_session

    async def execute(self, statement):
        return self.sync_session.execute(statement)

    def add(self, obj):
        self.sync_session.add(obj)

    async def flush(self):
        self.sync_session.flush()

    async def commit(self):
        self.sync_session.commit()

    async def refresh(self, obj):
        self.sync_session.refresh(obj)


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sync_session = sessionmaker(bind=engine, expire_on_commit=False)()
    return sync_session, AsyncSessionAdapter(sync_session)


def settings():
    return ScraperSettings(
        timeout_seconds=5,
        max_retries=0,
        concurrency_per_source=1,
        request_delay_min_ms=0,
        request_delay_max_ms=0,
        missing_threshold=2,
        removal_after_hours=9999,
        detail_ttl_hours=9999,
        max_pages=0,
        full_min_listing_ratio=0.5,
    )


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def pacheco_card(
    external_id: str,
    *,
    property_type: str = "Casa",
    price: str = "R$ 2.800.000,00",
    purpose: str = "sale",
    address: str = "R HERMES FONTES - VILA MADALENA",
    attrs: list[str] | None = None,
    post_id: str = "81572",
    images: list[str] | None = None,
) -> str:
    attrs = attrs or ["210 m²", "3 Dormitorios", "4 Banheiros", "2 Vagas"]
    images = images or [
        f"https://cdn.vistahost.com.br/zimmermann/vista.imobi/fotos/{external_id.split('-')[-1]}/foto-1.jpg",
        f"https://cdn.vistahost.com.br/zimmermann/vista.imobi/fotos/{external_id.split('-')[-1]}/foto-2.jpg",
    ]
    status = "Alugar" if purpose == "rent" else "Vender"
    image_html = "".join(f'<a href="{image}"><img src="{image}" /></a>' for image in images)
    attrs_html = "".join(f'<div class="infos__item"><p>{attr}</p></div>' for attr in attrs)
    return f"""
    <form class="imovel item" id="form-{post_id}" action="https://pacheco.com.br/visitar?action=add&imovel_id={post_id}&status={status}">
      <div class="box-img">{image_html}</div>
      <div class="box-txt">
        <div class="title"><h3>{address}</h3></div>
        <div class="infos">{attrs_html}</div>
        <p class="valor">{price}</p>
        <a class="box-txt__button" href="https://pacheco.com.br/imoveis/{external_id.lower()}/">Detalhes</a>
      </div>
      <div class="visitar"><p>{property_type} / {external_id}</p></div>
    </form>
    """


def listing(*cards: str, purpose: str = "sale", next_url: bool = False, reported_total: int | None = None) -> str:
    path = "alugar" if purpose == "rent" else "comprar"
    next_link = f'<a class="next page-numbers" href="https://pacheco.com.br/{path}/page/2/"></a>' if next_url else ""
    total = f"<p>{reported_total} Imóveis encontrados</p>" if reported_total is not None else ""
    return f'<html><body>{total}<div class="wrapper-imoveis" id="sticky">{"".join(cards)}</div>{next_link}</body></html>'


def empty_listing(*, purpose: str = "sale", reported_total: int | None = None) -> str:
    return listing(purpose=purpose, reported_total=reported_total)


async def run_engine(async_session, routes, *, mode="delta", purpose="sale", max_details=0, max_pages=None):
    def handler(request):
        path = request.url.path
        if path == "/comprar/":
            response = routes.get("listing:sale:1", empty_listing(purpose="sale"))
        elif path == "/comprar/page/2/":
            response = routes.get("listing:sale:2", empty_listing(purpose="sale"))
        elif path == "/alugar/":
            response = routes.get("listing:rent:1", empty_listing(purpose="rent"))
        elif path == "/alugar/page/2/":
            response = routes.get("listing:rent:2", empty_listing(purpose="rent"))
        else:
            external_id = path.rstrip("/").split("/")[-1].upper()
            response = routes.get(f"detail:{external_id}", routes.get("detail:default", ""))
        if isinstance(response, int):
            return httpx.Response(response, request=request)
        return httpx.Response(200, text=response, request=request)

    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    http_client = SharedScraperHTTPClient(settings(), client=async_client)
    try:
        return await SyncEngine(provider, settings(), session=async_session, http_client=http_client).run(
            mode=mode,
            search_scope={"purpose": purpose},
            dry_run=False,
            max_details=max_details,
            max_pages=max_pages,
        )
    finally:
        await async_client.aclose()


def props(sync_session):
    return sync_session.execute(select(Property)).scalars().all()


def prop_by_external_id(sync_session, external_id: str):
    return sync_session.execute(select(Property).where(Property.external_id == external_id)).scalars().one()


def offers_for(sync_session, prop):
    rows = sync_session.execute(
        select(PropertyOffer).where(PropertyOffer.property_id == prop.id).order_by(PropertyOffer.purpose)
    )
    return rows.scalars().all()


def events(sync_session, event_type: str | None = None):
    stmt = select(PropertyEvent)
    if event_type:
        stmt = stmt.where(PropertyEvent.event_type == event_type)
    return sync_session.execute(stmt).scalars().all()


def photos(sync_session, prop):
    rows = sync_session.execute(
        select(PropertyPhoto).where(PropertyPhoto.property_id == prop.id).order_by(PropertyPhoto.position)
    )
    return rows.scalars().all()


def source_by_key(sync_session, key: str):
    return sync_session.execute(select(Source).where(Source.key == key)).scalars().one()


def test_pacheco_sale_offer_detail_photos_and_lifecycle_without_internet():
    sync_session, async_session = make_session()
    sale_routes = {
        "listing:sale:1": listing(pacheco_card("Z-268289"), purpose="sale"),
        "detail:Z-268289": read_fixture("pacheco_detail.html"),
    }

    stats = asyncio.run(run_engine(async_session, sale_routes, mode="delta", purpose="sale", max_details=1))
    source = source_by_key(sync_session, "pacheco")
    prop = prop_by_external_id(sync_session, "Z-268289")
    offer = offers_for(sync_session, prop)[0]

    assert source.name == "Pacheco Imóveis"
    assert source.base_url == "https://pacheco.com.br"
    assert stats.new_properties == 1
    assert stats.offers_created == 1
    assert stats.photos_created == 19
    assert prop.source_id == source.id
    assert prop.external_id == "Z-268289"
    assert prop.city == "São Paulo"
    assert prop.property_type == "Casa"
    assert prop.price == Decimal("2800000.00")
    assert prop.property_tax == Decimal("2028.00")
    assert offer.purpose == "SALE"
    assert offer.price == Decimal("2800000.00")
    assert len(photos(sync_session, prop)) == 19
    assert prop.metadata_json["detail_raw_data"]["upstream_numeric_id"] == "268289"
    assert len(events(sync_session, "CREATED")) == 1

    stats = asyncio.run(run_engine(async_session, sale_routes, mode="delta", purpose="sale", max_details=0))
    assert stats.unchanged_properties == 1
    assert len(events(sync_session, "CREATED")) == 1

    changed_sale = {
        "listing:sale:1": listing(
            pacheco_card("Z-268289", price="R$ 2.700.000,00", post_id="99999"),
            purpose="sale",
        )
    }
    stats = asyncio.run(run_engine(async_session, changed_sale, mode="delta", purpose="sale", max_details=0))
    prop = prop_by_external_id(sync_session, "Z-268289")
    assert stats.updated_properties == 1
    assert prop.metadata_json["wordpress_post_id"] == "99999"
    price_events = events(sync_session, "PRICE_CHANGED")
    assert len(price_events) == 1
    assert price_events[0].new_value == {"entity": "offer", "purpose": "SALE", "price": "2700000.00"}

    missing = {"listing:sale:1": empty_listing(purpose="sale")}
    stats = asyncio.run(run_engine(async_session, missing, mode="full", purpose="sale", max_details=0))
    offer = offers_for(sync_session, prop)[0]
    assert stats.missing_offers == 1
    assert offer.status == "MISSING"
    assert prop_by_external_id(sync_session, "Z-268289").status == "MISSING"

    stats = asyncio.run(run_engine(async_session, missing, mode="full", purpose="sale", max_details=0))
    offer = offers_for(sync_session, prop)[0]
    assert stats.removed_offers == 1
    assert offer.status == "REMOVED"
    assert prop_by_external_id(sync_session, "Z-268289").status == "REMOVED"

    stats = asyncio.run(run_engine(async_session, sale_routes, mode="delta", purpose="sale", max_details=0))
    offer = offers_for(sync_session, prop)[0]
    assert stats.reactivated_properties == 1
    assert stats.reactivated_offers == 1
    assert offer.status == "ACTIVE"
    assert prop_by_external_id(sync_session, "Z-268289").status == "ACTIVE"
    assert len(events(sync_session, "REACTIVATED")) == 2


def test_pacheco_rent_offer_monthly_values_and_idempotency_without_internet():
    sync_session, async_session = make_session()
    rent_card = pacheco_card(
        "L1-50943",
        property_type="Loja",
        price="R$ 10.000,00",
        purpose="rent",
        address="R ASPICUELTA - VILA MADALENA",
        attrs=["80 m²", "4 Salas", "2 Banheiros", "1 Vaga"],
        post_id="98213",
        images=[
            "https://objectstorage.sa-saopaulo-1.oraclecloud.com/n/x/b/y/o/imovel/PI/PI4126/PI4126010.jpg",
            "https://objectstorage.sa-saopaulo-1.oraclecloud.com/n/x/b/y/o/imovel/PI/PI4126/PI4126002.jpg",
        ],
    )
    rent_routes = {
        "listing:rent:1": listing(rent_card, purpose="rent"),
        "detail:L1-50943": read_fixture("pacheco_rent_detail.html"),
    }

    stats = asyncio.run(run_engine(async_session, rent_routes, mode="delta", purpose="rent", max_details=1))
    prop = prop_by_external_id(sync_session, "L1-50943")
    offer = offers_for(sync_session, prop)[0]

    assert stats.new_properties == 1
    assert stats.offers_created == 1
    assert stats.rent_offers_seen == 1
    assert prop.property_type == "Loja"
    assert prop.price == Decimal("10000.00")
    assert prop.property_tax == Decimal("467.15")
    assert offer.purpose == "RENT"
    assert offer.price == Decimal("10000.00")
    assert len(photos(sync_session, prop)) == 8
    assert prop.metadata_json["detail_raw_data"]["advertised_monthly_total"] == "10467.15"
    assert prop.metadata_json["detail_raw_data"]["property_tax_period"] == "monthly"
    assert "Ar condicionado" in prop.metadata_json["property_features"]

    stats = asyncio.run(run_engine(async_session, rent_routes, mode="delta", purpose="rent", max_details=0))
    assert stats.unchanged_properties == 1
    assert len(events(sync_session, "PRICE_CHANGED")) == 0


def test_pacheco_listing_gallery_is_persisted_when_detail_is_not_fetched():
    sync_session, async_session = make_session()
    routes = {
        "listing:sale:1": listing(
            pacheco_card(
                "V1-51824",
                property_type="Casa",
                price="R$ 950.000,00",
                images=["https://cdn.example.com/v1-1.jpg", "https://cdn.example.com/v1-2.jpg"],
            ),
            purpose="sale",
        )
    }

    stats = asyncio.run(run_engine(async_session, routes, mode="delta", purpose="sale", max_details=0))
    prop = prop_by_external_id(sync_session, "V1-51824")

    assert stats.new_properties == 1
    assert stats.photos_created == 2
    assert [photo.source_url for photo in photos(sync_session, prop)] == [
        "https://cdn.example.com/v1-1.jpg",
        "https://cdn.example.com/v1-2.jpg",
    ]


def test_pacheco_full_partial_runs_do_not_reconcile_offers():
    sync_session, async_session = make_session()
    initial = {"listing:sale:1": listing(pacheco_card("Z-268289"), purpose="sale")}
    asyncio.run(run_engine(async_session, initial, mode="delta", purpose="sale", max_details=0))
    prop = prop_by_external_id(sync_session, "Z-268289")

    limited = {
        "listing:sale:1": listing(
            pacheco_card("V1-51824", price="R$ 950.000,00"),
            purpose="sale",
            next_url=True,
        )
    }
    stats = asyncio.run(run_engine(async_session, limited, mode="full", purpose="sale", max_details=0, max_pages=1))
    assert stats.completed is False
    assert stats.stopped_reason == "max_pages"
    assert offers_for(sync_session, prop)[0].status == "ACTIVE"

    suspicious = {"listing:sale:1": empty_listing(purpose="sale", reported_total=14615)}
    stats = asyncio.run(run_engine(async_session, suspicious, mode="full", purpose="sale", max_details=0))
    assert stats.completed is False
    assert stats.stopped_reason == "parse_error"
    assert offers_for(sync_session, prop)[0].status == "ACTIVE"

    repeated = {
        "listing:sale:1": listing(pacheco_card("Z-268289"), purpose="sale", next_url=True),
        "listing:sale:2": listing(pacheco_card("Z-268289"), purpose="sale"),
    }
    stats = asyncio.run(run_engine(async_session, repeated, mode="full", purpose="sale", max_details=0))
    assert stats.completed is False
    assert stats.stopped_reason == "repeated_page"
    assert offers_for(sync_session, prop)[0].status == "ACTIVE"


def test_pacheco_sale_and_rent_scopes_reconcile_independently():
    sync_session, async_session = make_session()
    sale_routes = {"listing:sale:1": listing(pacheco_card("Z-268289"), purpose="sale")}
    rent_routes = {
        "listing:rent:1": listing(
            pacheco_card(
                "Z-268289",
                price="R$ 9.000,00",
                purpose="rent",
                attrs=["210 m²", "3 Dormitorios", "4 Banheiros", "2 Vagas"],
            ),
            purpose="rent",
        )
    }

    asyncio.run(run_engine(async_session, sale_routes, mode="delta", purpose="sale", max_details=0))
    asyncio.run(run_engine(async_session, rent_routes, mode="delta", purpose="rent", max_details=0))
    prop = prop_by_external_id(sync_session, "Z-268289")
    assert [(offer.purpose, offer.price, offer.status) for offer in offers_for(sync_session, prop)] == [
        ("RENT", Decimal("9000.00"), "ACTIVE"),
        ("SALE", Decimal("2800000.00"), "ACTIVE"),
    ]

    asyncio.run(run_engine(async_session, {"listing:sale:1": empty_listing(purpose="sale")}, mode="full", purpose="sale"))
    assert {offer.purpose: offer.status for offer in offers_for(sync_session, prop)} == {
        "RENT": "ACTIVE",
        "SALE": "MISSING",
    }
    assert prop_by_external_id(sync_session, "Z-268289").status == "ACTIVE"


def test_pacheco_identity_keys_do_not_merge_prefixes_or_sources():
    sync_session, async_session = make_session()
    routes = {
        "listing:sale:1": listing(
            pacheco_card("Z-268289", price="R$ 2.800.000,00"),
            pacheco_card("V1-268289", price="R$ 950.000,00", post_id="77777"),
            purpose="sale",
        )
    }
    asyncio.run(run_engine(async_session, routes, mode="delta", purpose="sale", max_details=0))

    pacheco_source = source_by_key(sync_session, "pacheco")
    zimmermann = Source(
        key="zimoveis",
        name="Zimmermann Imóveis",
        base_url="https://www.zimoveis.com.br",
        enabled=True,
    )
    sync_session.add(zimmermann)
    sync_session.flush()
    sync_session.add(
        Property(
            external_id="268289",
            source_id=zimmermann.id,
            source_url="https://www.zimoveis.com.br/imovel/268289",
            url="https://www.zimoveis.com.br/imovel/268289",
            status="ACTIVE",
        )
    )
    sync_session.commit()

    assert {prop.external_id for prop in props(sync_session) if prop.source_id == pacheco_source.id} == {
        "Z-268289",
        "V1-268289",
    }
    assert sync_session.execute(
        select(Property).where(Property.source_id == zimmermann.id, Property.external_id == "268289")
    ).scalars().one()
