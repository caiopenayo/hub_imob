import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, String, Text, Integer, Numeric, DateTime, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

def utc_now() -> datetime:
    return datetime.utcnow()

# Tabela que representa as fontes dos anúncios, como imobiliárias ou sites
class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str | None] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

# Tabela principal de imóveis coletados
class Property(Base):
    __tablename__ = "properties"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_properties_source_external"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("sources.id"), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    transaction_type: Mapped[str | None] = mapped_column(String(50))
    property_type: Mapped[str | None] = mapped_column(String(100))
    property_subtype: Mapped[str | None] = mapped_column(String(100))
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    price_currency: Mapped[str | None] = mapped_column(String(3), default="BRL")
    condominium_fee: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    property_tax: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    price_per_m2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    address_line: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    neighborhood: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str | None] = mapped_column(String(50), default="BR")
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    bedrooms: Mapped[int | None] = mapped_column(Integer)
    suites: Mapped[int | None] = mapped_column(Integer)
    bathrooms: Mapped[int | None] = mapped_column(Integer)
    parking_spaces: Mapped[int | None] = mapped_column(Integer)
    area_m2: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    main_image_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(20), default="ACTIVE")
    content_hash: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime, default=utc_now)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, default=utc_now)
    missing_since: Mapped[datetime | None] = mapped_column(DateTime)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime)
    detail_last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    offers: Mapped[list["PropertyOffer"]] = relationship(
        "PropertyOffer",
        back_populates="property",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    photos: Mapped[list["PropertyPhoto"]] = relationship(
        "PropertyPhoto",
        back_populates="property",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="PropertyPhoto.position",
    )


class PropertyOffer(Base):
    __tablename__ = "property_offers"
    __table_args__ = (
        UniqueConstraint("property_id", "purpose", name="uq_property_offers_property_purpose"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
    )
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3), default="BRL")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    content_hash: Mapped[str | None] = mapped_column(String(64))
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime, default=utc_now)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, default=utc_now)
    missing_since: Mapped[datetime | None] = mapped_column(DateTime)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    property: Mapped["Property"] = relationship("Property", back_populates="offers")


class PropertyPhoto(Base):
    __tablename__ = "property_photos"
    __table_args__ = (
        UniqueConstraint("property_id", "source_url", name="uq_property_photos_property_source_url"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    property: Mapped["Property"] = relationship("Property", back_populates="photos")


class PropertyEvent(Base):
    __tablename__ = "property_events"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    crawl_run_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("jobs_logs.id"))

# Tabela que registra os jobs de scraping executados, incluindo status e resultados
class JobLog(Base):
    __tablename__ = "jobs_logs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("sources.id"))
    provider_key: Mapped[str | None] = mapped_column(String(100))
    source_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    search_scope: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="delta")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    listings_seen: Mapped[int] = mapped_column(Integer, default=0)
    new_properties: Mapped[int] = mapped_column(Integer, default=0)
    updated_properties: Mapped[int] = mapped_column(Integer, default=0)
    unchanged_properties: Mapped[int] = mapped_column(Integer, default=0)
    missing_properties: Mapped[int] = mapped_column(Integer, default=0)
    removed_properties: Mapped[int] = mapped_column(Integer, default=0)
    reactivated_properties: Mapped[int] = mapped_column(Integer, default=0)
    detail_pages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    http_errors: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    parse_errors: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
