import asyncio
from decimal import Decimal

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.db.crud import get_property_price_history
from backend.app.db.models import Base, Property, PropertyEvent, PropertyPhoto
from scrapers.core.engine import SyncEngine
from scrapers.core.http import SharedScraperHTTPClient
from scrapers.core.settings import ScraperSettings
from scrapers.sources.zimoveis import provider


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
        detail_ttl_hours=0,
        max_pages=0,
        full_min_listing_ratio=0.5,
    )


def card(external_id, price, address, image="/fotos/thumb.jpg"):
    return f"""
    <div class="cardImovel" data-code="{external_id}">
      <a href="/imovel/apartamento/padrao/perdizes/sao-paulo/{address}/{external_id}">
        <img src="{image}?ts={external_id}">
      </a>
      <a aria-label="Acessar mais informações sobre o imóvel em Perdizes">Perdizes</a>
      <div><!-- Tipo e Valor --><span>Apartamento</span><strong>{price}</strong></div>
      <address>{address.replace("-", " ").title()}</address>
      <span>100 m²</span><span>3 dorms</span><span>1 suíte</span><span>2 vagas</span>
    </div>
    """


def listing(*cards):
    return f"<html><body>{''.join(cards)}</body></html>"


def empty_listing():
    return '<div class="rowScroolPage-2"></div>'


def detail(external_id, price, images):
    gallery = "\n".join(
        f'<a data-fancybox="galeria" href="{image}?ts={external_id}"><img src="{image}-thumb"></a>'
        for image in images
    )
    return f"""
    <html>
      <head>
        <title>Apartamento à Venda em Perdizes - {external_id}</title>
        <link rel="canonical" href="https://www.zimoveis.com.br/imovel/apartamento/padrao/perdizes/sao-paulo/rua-x/{external_id}">
        <meta property="og:image" content="{images[0]}?ts={external_id}">
      </head>
      <body>
        <dl>
          <dt>Código:</dt><dd>{external_id}</dd>
          <dt>Valor:</dt><dd>{price}</dd>
          <dt>Valor por m²:</dt><dd>R$ 10.000</dd>
          <dt>Bairro:</dt><dd>Perdizes</dd>
          <dt>Endereço:</dt><dd>Rua X</dd>
          <dt>Condomínio:</dt><dd>R$ 1.000</dd>
          <dt>IPTU:</dt><dd>R$ 500</dd>
          <dt>Dormitórios:</dt><dd>3</dd>
          <dt>Suítes:</dt><dd>1</dd>
          <dt>Vagas:</dt><dd>2</dd>
          <dt>Área útil:</dt><dd>100 m²</dd>
        </dl>
        <section><h2>Sobre o imóvel</h2><p>Descrição {external_id}</p></section>
        <section><h2>Detalhes do imóvel</h2><ul><li>Varanda</li></ul></section>
        {gallery}
      </body>
    </html>
    """


async def run_engine(async_session, routes, mode="delta"):
    def handler(request):
        if "/buscar-imoveis" in str(request.url):
            page = request.url.params.get("page", "1")
            response = routes.get(f"listing:{page}", empty_listing())
            if isinstance(response, int):
                return httpx.Response(response, request=request)
            return httpx.Response(200, text=response, request=request)
        external_id = request.url.path.rstrip("/").split("/")[-1]
        return httpx.Response(200, text=routes[f"detail:{external_id}"], request=request)

    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    http_client = SharedScraperHTTPClient(settings(), client=async_client)
    try:
        return await SyncEngine(provider, settings(), session=async_session, http_client=http_client).run(
            mode=mode,
            search_scope={"q": "Sao Paulo"},
            dry_run=False,
            max_details=20,
        )
    finally:
        await async_client.aclose()


def props_by_external_id(sync_session):
    props = sync_session.execute(select(Property)).scalars().all()
    return {prop.external_id: prop for prop in props}


def events(sync_session, event_type=None):
    stmt = select(PropertyEvent)
    if event_type:
        stmt = stmt.where(PropertyEvent.event_type == event_type)
    return sync_session.execute(stmt).scalars().all()


def photos(sync_session, prop):
    return sync_session.execute(select(PropertyPhoto).where(PropertyPhoto.property_id == prop.id)).scalars().all()


def test_sync_engine_end_to_end_without_internet():
    sync_session, async_session = make_session()

    first = {
        "listing:1": listing(
            card("1001", "R$ 3.100.000", "rua-a", "/fotos/1001-a"),
            card("1002", "R$ 2.000.000", "rua-b", "/fotos/1002-a"),
        ),
        "listing:2": empty_listing(),
        "detail:1001": detail("1001", "R$ 3.100.000", ["/fotos/1001-a", "/fotos/1001-b"]),
        "detail:1002": detail("1002", "R$ 2.000.000", ["/fotos/1002-a"]),
    }
    stats = asyncio.run(run_engine(async_session, first, mode="delta"))
    assert stats.new_properties == 2
    assert len(events(sync_session, "CREATED")) == 2

    second = {
        "listing:1": listing(
            card("1001", "R$ 2.950.000", "rua-a", "/fotos/1001-a"),
            card("1002", "R$ 2.000.000", "rua-b", "/fotos/1002-a"),
            card("1003", "R$ 1.500.000", "rua-c", "/fotos/1003-a"),
        ),
        "listing:2": empty_listing(),
        "detail:1001": detail("1001", "R$ 2.950.000", ["/fotos/1001-a", "/fotos/1001-c"]),
        "detail:1002": detail("1002", "R$ 2.000.000", ["/fotos/1002-a"]),
        "detail:1003": detail("1003", "R$ 1.500.000", ["/fotos/1003-a"]),
    }
    stats = asyncio.run(run_engine(async_session, second, mode="delta"))
    assert stats.new_properties == 1
    assert stats.updated_properties == 1
    assert stats.unchanged_properties == 1
    assert len(events(sync_session, "PRICE_CHANGED")) == 1

    stats = asyncio.run(run_engine(async_session, second, mode="delta"))
    assert stats.new_properties == 0
    assert stats.updated_properties == 0
    assert stats.unchanged_properties == 3
    assert len(events(sync_session, "PRICE_CHANGED")) == 1

    props = props_by_external_id(sync_session)
    prop_1001 = props["1001"]
    prop_1001_photos = {photo.source_url: photo for photo in photos(sync_session, prop_1001)}
    assert prop_1001_photos["https://www.zimoveis.com.br/fotos/1001-a?ts=1001"].is_active is True
    assert prop_1001_photos["https://www.zimoveis.com.br/fotos/1001-b?ts=1001"].is_active is False
    assert prop_1001_photos["https://www.zimoveis.com.br/fotos/1001-c?ts=1001"].is_active is True

    full_missing = {
        "listing:1": listing(
            card("1001", "R$ 2.950.000", "rua-a", "/fotos/1001-a"),
            card("1003", "R$ 1.500.000", "rua-c", "/fotos/1003-a"),
        ),
        "listing:2": empty_listing(),
        "detail:1001": detail("1001", "R$ 2.950.000", ["/fotos/1001-a", "/fotos/1001-c"]),
        "detail:1003": detail("1003", "R$ 1.500.000", ["/fotos/1003-a"]),
    }
    stats = asyncio.run(run_engine(async_session, full_missing, mode="full"))
    assert stats.missing_properties == 1
    assert props_by_external_id(sync_session)["1002"].status == "MISSING"
    assert len(events(sync_session, "MARKED_MISSING")) == 1

    stats = asyncio.run(run_engine(async_session, full_missing, mode="full"))
    assert stats.removed_properties == 1
    assert props_by_external_id(sync_session)["1002"].status == "REMOVED"
    assert len(events(sync_session, "REMOVED")) == 1

    reappears = {
        "listing:1": listing(
            card("1001", "R$ 2.950.000", "rua-a", "/fotos/1001-a"),
            card("1002", "R$ 2.000.000", "rua-b", "/fotos/1002-a"),
            card("1003", "R$ 1.500.000", "rua-c", "/fotos/1003-a"),
        ),
        "listing:2": empty_listing(),
        "detail:1001": detail("1001", "R$ 2.950.000", ["/fotos/1001-a", "/fotos/1001-c"]),
        "detail:1002": detail("1002", "R$ 2.000.000", ["/fotos/1002-a"]),
        "detail:1003": detail("1003", "R$ 1.500.000", ["/fotos/1003-a"]),
    }
    stats = asyncio.run(run_engine(async_session, reappears, mode="delta"))
    assert stats.reactivated_properties == 1
    assert props_by_external_id(sync_session)["1002"].status == "ACTIVE"
    assert len(events(sync_session, "REACTIVATED")) == 1

    partial = {
        "listing:1": listing(card("1001", "R$ 2.950.000", "rua-a", "/fotos/1001-a")),
        "listing:2": 429,
        "detail:1001": detail("1001", "R$ 2.950.000", ["/fotos/1001-a"]),
    }
    stats = asyncio.run(run_engine(async_session, partial, mode="full"))
    assert stats.completed is False
    assert props_by_external_id(sync_session)["1002"].status == "ACTIVE"

    history = asyncio.run(get_property_price_history(async_session, prop_1001.id))
    assert [Decimal(str(item["price"])) for item in history] == [Decimal("3100000.00"), Decimal("2950000.00")]
