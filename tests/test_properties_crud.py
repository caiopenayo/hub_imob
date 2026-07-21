import asyncio
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.db.crud import list_properties
from backend.app.db.models import Base, Property, Source


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
    sync_session.add(
        Property(
            external_id=external_id,
            source_id=source.id,
            url=f"https://example.com/{external_id}",
            source_url=f"https://example.com/{external_id}",
            title=f"Property {external_id}",
            city="São Paulo",
            property_subtype=subtype,
            status="ACTIVE",
        )
    )


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
