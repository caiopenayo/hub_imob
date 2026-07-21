import asyncio
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.api.routes.properties import serialize_property
from backend.app.db.crud import list_properties
from backend.app.db.models import Base, Property, PropertyPhoto, Source


class AsyncSessionAdapter:
    def __init__(self, sync_session):
        self.sync_session = sync_session

    async def execute(self, statement):
        return self.sync_session.execute(statement)

    def add(self, obj):
        self.sync_session.add(obj)

    async def flush(self):
        self.sync_session.flush()


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sync_session = sessionmaker(bind=engine, expire_on_commit=False)()
    return sync_session, AsyncSessionAdapter(sync_session)


def add_property(sync_session, source, external_id, subtype):
    prop = Property(
        external_id=external_id,
        source_id=source.id,
        url=f"https://example.com/{external_id}",
        source_url=f"https://example.com/{external_id}",
        title=f"Property {external_id}",
        city="São Paulo",
        property_subtype=subtype,
        status="ACTIVE",
    )
    sync_session.add(prop)
    return prop


def test_list_properties_hides_commercial_inventory():
    sync_session, async_session = make_session()
    source = Source(
        id=uuid.uuid4(),
        key="localimoveis",
        name="Local Imóveis",
        base_url="https://www.localimoveis.com.br",
        enabled=True,
    )
    sync_session.add(source)
    add_property(sync_session, source, "residential", "Residencial")
    add_property(sync_session, source, "commercial", "Comercial")
    add_property(sync_session, source, "unknown", None)
    sync_session.commit()

    items, total = asyncio.run(list_properties(async_session, city="São Paulo"))

    assert total == 2
    assert {item.external_id for item in items} == {"residential", "unknown"}


def test_property_serialization_uses_active_photo_table_gallery():
    sync_session, async_session = make_session()
    source = Source(
        id=uuid.uuid4(),
        key="pacheco",
        name="Pacheco Imóveis",
        base_url="https://pacheco.com.br",
        enabled=True,
    )
    sync_session.add(source)
    prop = add_property(sync_session, source, "with-photos", "Residencial")
    prop.main_image_url = "https://cdn.example.com/main.jpg"
    prop.metadata_json = {"images": ["https://cdn.example.com/stale.jpg"]}
    sync_session.flush()
    sync_session.add_all(
        [
            PropertyPhoto(property_id=prop.id, source_url="https://cdn.example.com/one.jpg", position=1, is_active=True),
            PropertyPhoto(property_id=prop.id, source_url="https://cdn.example.com/two.jpg", position=2, is_active=True),
            PropertyPhoto(property_id=prop.id, source_url="https://cdn.example.com/old.jpg", position=3, is_active=False),
        ]
    )
    sync_session.commit()

    items, total = asyncio.run(list_properties(async_session, city="São Paulo"))
    serialized = serialize_property(items[0])

    assert total == 1
    assert serialized.metadata["images"] == [
        "https://cdn.example.com/one.jpg",
        "https://cdn.example.com/two.jpg",
    ]
    assert serialized.metadata["main_image"] == "https://cdn.example.com/one.jpg"


def test_property_serialization_prefers_full_zimoveis_photo_over_generated_thumb():
    sync_session, async_session = make_session()
    source = Source(
        id=uuid.uuid4(),
        key="zimoveis",
        name="Zimmermann Imóveis",
        base_url="https://www.zimoveis.com.br",
        enabled=True,
    )
    sync_session.add(source)
    prop = add_property(sync_session, source, "290330", "Duplex")
    prop.main_image_url = "https://www.zimoveis.com.br/thumb/290330/cobertura-duplex_290330_1_1920x1080.webp?ts=1"
    sync_session.flush()
    sync_session.add_all(
        [
            PropertyPhoto(
                property_id=prop.id,
                source_url="https://www.zimoveis.com.br/thumb/290330/cobertura-duplex_290330_1_1920x1080.webp?ts=1",
                position=1,
                is_active=True,
            ),
            PropertyPhoto(
                property_id=prop.id,
                source_url="https://cdn.vistahost.com.br/zimmermann/vista.imobi/fotos/290330/i99N48_2903306a2032018bc53.jpg",
                position=2,
                is_active=True,
            ),
        ]
    )
    sync_session.commit()

    items, total = asyncio.run(list_properties(async_session, city="São Paulo"))
    serialized = serialize_property(items[0])

    assert total == 1
    assert serialized.main_image_url == (
        "https://cdn.vistahost.com.br/zimmermann/vista.imobi/fotos/290330/i99N48_2903306a2032018bc53.jpg"
    )
    assert serialized.metadata["images"] == [
        "https://cdn.vistahost.com.br/zimmermann/vista.imobi/fotos/290330/i99N48_2903306a2032018bc53.jpg"
    ]
