'''Define os formatos de entrada e saída de dados para a API relacionados a imóveis (Property)'''
from typing import Optional
from datetime import datetime
from uuid import UUID
from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class PropertyBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: Optional[str] = None
    description: Optional[str] = None
    transaction_type: Optional[str] = None
    property_type: Optional[str] = None
    property_subtype: Optional[str] = None
    price: Optional[float] = None
    price_currency: Optional[str] = "BRL"
    condominium_fee: Optional[float] = None
    property_tax: Optional[float] = None
    price_per_m2: Optional[float] = None
    address_line: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    neighborhood: Optional[str] = None
    bedrooms: Optional[int] = None
    suites: Optional[int] = None
    bathrooms: Optional[int] = None
    parking_spaces: Optional[int] = None
    area_m2: Optional[float] = None
    main_image_url: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    status: Optional[str] = None
    metadata: Optional[dict] = Field(
        default=None,
        validation_alias=AliasChoices("metadata_json", "metadata"),
    )


class PropertyOfferRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    purpose: str
    price: Optional[float] = None
    currency: Optional[str] = "BRL"
    status: str
    content_hash: Optional[str] = None
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    missing_since: Optional[datetime] = None
    removed_at: Optional[datetime] = None
    metadata: Optional[dict] = Field(
        default=None,
        validation_alias=AliasChoices("metadata_json", "metadata"),
    )


class PropertyCreate(PropertyBase):
    external_id: str
    source_id: UUID
    url: str
    source_url: Optional[str] = None


class PropertyRead(PropertyBase):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    external_id: str
    source_id: UUID
    url: str
    source_url: Optional[str] = None
    content_hash: Optional[str] = None
    offers: list[PropertyOfferRead] = Field(default_factory=list)


class PropertyList(BaseModel):
    items: list[PropertyRead]
    meta: dict


class PriceHistoryItem(BaseModel):
    price: float
    detected_at: datetime
