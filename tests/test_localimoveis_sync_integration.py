import asyncio
from decimal import Decimal
from pathlib import Path

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.db.models import Base, Property, PropertyEvent, PropertyOffer, PropertyPhoto
from scrapers.core.engine import SyncEngine
from scrapers.core.http import SharedScraperHTTPClient
from scrapers.core.settings import ScraperSettings
from scrapers.sources.localimoveis import provider


FIXTURES = Path(__file__).parent / "fixtures" / "localimoveis"


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


def local_card(
    external_id: str,
    sale_price: str | None = None,
    rent_price: str | None = None,
    *,
    area: str = "332 m²",
    bedrooms: str = "4 Quartos",
    parking: str = "4 Vagas",
    neighborhood: str = "PINHEIROS",
    property_type: str = "APARTAMENTO - RESIDENCIAL",
) -> str:
    href = (
        "https://www.localimoveis.com.br/imovel/"
        f"apartamento-a-venda-sao-paulo-pinheiros-332m2-4dormitorios-4vagas/{external_id}"
    )
    offers = []
    if rent_price:
        offers.append(f"<h3>Aluguel</h3><h2>{rent_price}</h2>")
    if sale_price:
        offers.append(f"<h3>Venda</h3><h2>{sale_price}</h2>")
    return f"""
    <div class="card-imovel">
      <a href="{href}">
        <div class="card-foto" style="background-image: url('https://betaimages.lopes.com.br/realestate/REO{external_id}/foto.JPG')"></div>
      </a>
      <div class="info"><div class="largura">
        <div class="colunaTipo1"><h2>{property_type}</h2></div>
        <h2 class="refDireita1"><span>Cod: {external_id}</span></h2>
        <h3>{neighborhood}</h3>
        <div class="retorno">
          <div class="texto"><label>{area}</label><label>Área útil</label></div>
          <div class="texto"><label class="one">{bedrooms}</label></div>
          <div class="texto"><label class="one">{parking}</label></div>
        </div>
        <div class="bloco-valores">{''.join(offers)}</div>
        <a class="link" href="{href}">Conhecer</a>
      </div></div>
    </div>
    """


def listing(*cards: str, next_url: bool = False, reported_total: int | None = None) -> str:
    next_link = '<link rel="next" href="/imoveis/venda/sp/sao-paulo/2">' if next_url else ""
    total = f"<h1>{reported_total} Resultados</h1>" if reported_total is not None else ""
    return f"<html><head>{next_link}</head><body>{total}{''.join(cards)}</body></html>"


def detail_6485() -> str:
    return (FIXTURES / "detail_6485.html").read_text(encoding="utf-8")


async def run_engine(async_session, routes, *, mode="delta", max_details=0, max_pages=None, search_scope=None):
    def handler(request):
        path = request.url.path
        if path.endswith("/imoveis/venda/sp/sao-paulo"):
            response = routes.get("listing:1", listing())
        elif path.endswith("/imoveis/venda/sp/sao-paulo/2"):
            response = routes.get("listing:2", listing())
        else:
            external_id = path.rstrip("/").split("/")[-1]
            response = routes.get(f"detail:{external_id}", routes.get("detail:default", ""))
        if isinstance(response, int):
            return httpx.Response(response, request=request)
        return httpx.Response(200, text=response, request=request)

    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    http_client = SharedScraperHTTPClient(settings(), client=async_client)
    try:
        return await SyncEngine(provider, settings(), session=async_session, http_client=http_client).run(
            mode=mode,
            search_scope=search_scope or {"state_slug": "sp", "city_slug": "sao-paulo", "purpose": "sale"},
            dry_run=False,
            max_details=max_details,
            max_pages=max_pages,
        )
    finally:
        await async_client.aclose()


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
    rows = sync_session.execute(select(PropertyPhoto).where(PropertyPhoto.property_id == prop.id))
    return rows.scalars().all()


def test_localimoveis_sync_offers_lifecycle_without_internet():
    sync_session, async_session = make_session()

    first = {
        "listing:1": listing(local_card("6485", sale_price="R$ 8.850.000,00")),
        "detail:6485": detail_6485(),
    }
    stats = asyncio.run(run_engine(async_session, first, mode="delta", max_details=1))
    prop_6485 = prop_by_external_id(sync_session, "6485")
    offer_6485 = offers_for(sync_session, prop_6485)[0]

    assert stats.new_properties == 1
    assert stats.offers_created == 1
    assert offer_6485.purpose == "SALE"
    assert offer_6485.price == Decimal("8850000.00")
    assert len(photos(sync_session, prop_6485)) == 34
    assert len((prop_6485.metadata_json or {})["property_features"]) == 8

    stats = asyncio.run(run_engine(async_session, first, mode="delta", max_details=0))
    assert stats.unchanged_properties == 1
    assert len(events(sync_session, "CREATED")) == 1

    changed_sale = {
        "listing:1": listing(local_card("6485", sale_price="R$ 8.500.000,00")),
    }
    stats = asyncio.run(run_engine(async_session, changed_sale, mode="delta", max_details=0))
    assert stats.updated_properties == 1
    price_events = events(sync_session, "PRICE_CHANGED")
    assert len(price_events) == 1
    assert price_events[0].new_value == {"entity": "offer", "purpose": "SALE", "price": "8500000.00"}

    mixed = {
        "listing:1": listing(
            local_card("6485", sale_price="R$ 8.500.000,00"),
            local_card("18197", sale_price="R$ 4.500.000,00", rent_price="R$ 20.000,00", property_type="SALAS - COMERCIAL"),
        ),
    }
    stats = asyncio.run(run_engine(async_session, mixed, mode="delta", max_details=0))
    prop_18197 = prop_by_external_id(sync_session, "18197")
    offers_18197 = offers_for(sync_session, prop_18197)
    assert stats.new_properties == 1
    assert [(offer.purpose, offer.price, offer.status) for offer in offers_18197] == [
        ("RENT", Decimal("20000.00"), "ACTIVE"),
        ("SALE", Decimal("4500000.00"), "ACTIVE"),
    ]

    sale_missing = {
        "listing:1": listing(local_card("6485", sale_price="R$ 8.500.000,00")),
    }
    stats = asyncio.run(run_engine(async_session, sale_missing, mode="full", max_details=0))
    offers_18197 = offers_for(sync_session, prop_18197)
    assert stats.missing_offers == 1
    assert {offer.purpose: offer.status for offer in offers_18197} == {"RENT": "ACTIVE", "SALE": "MISSING"}
    assert prop_by_external_id(sync_session, "18197").status == "ACTIVE"

    stats = asyncio.run(run_engine(async_session, sale_missing, mode="full", max_details=0))
    offers_18197 = offers_for(sync_session, prop_18197)
    assert stats.removed_offers == 1
    assert {offer.purpose: offer.status for offer in offers_18197} == {"RENT": "ACTIVE", "SALE": "REMOVED"}
    assert prop_by_external_id(sync_session, "18197").status == "ACTIVE"

    stats = asyncio.run(run_engine(async_session, mixed, mode="delta", max_details=0))
    offers_18197 = offers_for(sync_session, prop_18197)
    assert stats.reactivated_offers == 1
    assert {offer.purpose: offer.status for offer in offers_18197} == {"RENT": "ACTIVE", "SALE": "ACTIVE"}
    assert len(events(sync_session, "REACTIVATED")) == 1


def test_localimoveis_operational_sale_scope_filters_rent_offers_without_internet():
    sync_session, async_session = make_session()
    mixed_scope = {
        "state_slug": "sp",
        "city_slug": "sao-paulo",
        "purpose": "sale",
        "sync_offer_purposes": ["sale"],
    }
    routes = {
        "listing:1": listing(local_card("18197", sale_price="R$ 4.500.000,00", rent_price="R$ 20.000,00")),
    }

    stats = asyncio.run(run_engine(async_session, routes, mode="delta", max_details=0, search_scope=mixed_scope))
    prop = prop_by_external_id(sync_session, "18197")
    offers = offers_for(sync_session, prop)

    assert stats.new_properties == 1
    assert stats.sale_offers_seen == 1
    assert stats.rent_offers_seen == 0
    assert [(offer.purpose, offer.price, offer.status) for offer in offers] == [
        ("SALE", Decimal("4500000.00"), "ACTIVE"),
    ]


def test_localimoveis_partial_full_does_not_reconcile_offers():
    sync_session, async_session = make_session()
    mixed = {
        "listing:1": listing(
            local_card("18197", sale_price="R$ 4.500.000,00", rent_price="R$ 20.000,00", property_type="SALAS - COMERCIAL"),
        ),
    }
    asyncio.run(run_engine(async_session, mixed, mode="delta", max_details=0))
    prop_18197 = prop_by_external_id(sync_session, "18197")

    limited = {
        "listing:1": listing(local_card("6485", sale_price="R$ 8.500.000,00"), next_url=True),
        "listing:2": listing(local_card("9999", sale_price="R$ 1.000.000,00")),
    }
    stats = asyncio.run(run_engine(async_session, limited, mode="full", max_details=0, max_pages=1))
    assert stats.completed is False
    assert stats.stopped_reason == "max_pages"
    assert {offer.purpose: offer.status for offer in offers_for(sync_session, prop_18197)} == {
        "RENT": "ACTIVE",
        "SALE": "ACTIVE",
    }

    repeated = {
        "listing:1": listing(local_card("6485", sale_price="R$ 8.500.000,00"), next_url=True),
        "listing:2": listing(local_card("6485", sale_price="R$ 8.500.000,00")),
    }
    stats = asyncio.run(run_engine(async_session, repeated, mode="full", max_details=0))
    assert stats.completed is False
    assert stats.stopped_reason == "repeated_page"
    assert {offer.purpose: offer.status for offer in offers_for(sync_session, prop_18197)} == {
        "RENT": "ACTIVE",
        "SALE": "ACTIVE",
    }
