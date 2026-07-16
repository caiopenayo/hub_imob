from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal


SyncMode = Literal["delta", "full"]
RunStatus = Literal["pending", "running", "success", "partial", "failed"]
PropertyStatus = Literal["ACTIVE", "MISSING", "REMOVED"]
PropertyEventType = Literal[
    "CREATED",
    "PRICE_CHANGED",
    "CONTENT_CHANGED",
    "MARKED_MISSING",
    "REMOVED",
    "REACTIVATED",
]


@dataclass(frozen=True)
class ScrapeRequest:
    url: str
    method: str = "GET"
    params: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class PropertyCandidate:
    source_key: str
    external_id: str
    source_url: str
    title: str | None = None
    transaction_type: str | None = None
    property_type: str | None = None
    property_subtype: str | None = None
    city: str | None = None
    state: str | None = None
    neighborhood: str | None = None
    address_line: str | None = None
    price: Decimal | None = None
    currency: str | None = "BRL"
    bedrooms: int | None = None
    suites: int | None = None
    bathrooms: int | None = None
    parking_spaces: int | None = None
    area_m2: Decimal | None = None
    main_image_url: str | None = None
    tags: list[str] = field(default_factory=list)
    raw_data: dict[str, Any] = field(default_factory=dict)
    discovered_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PropertyDetail:
    external_id: str
    description: str | None = None
    condominium_fee: Decimal | None = None
    property_tax: Decimal | None = None
    price_per_m2: Decimal | None = None
    image_urls: list[str] = field(default_factory=list)
    property_features: list[str] = field(default_factory=list)
    condominium_features: list[str] = field(default_factory=list)
    nearby_points: list[str] = field(default_factory=list)
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    video_urls: list[str] = field(default_factory=list)
    virtual_tour_url: str | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ListingPage:
    candidates: list[PropertyCandidate] = field(default_factory=list)
    next_page: int | None = None
    is_complete: bool = True


@dataclass
class SyncStats:
    provider_key: str
    mode: SyncMode
    dry_run: bool = False
    pages_fetched: int = 0
    listings_seen: int = 0
    new_properties: int = 0
    updated_properties: int = 0
    unchanged_properties: int = 0
    missing_properties: int = 0
    removed_properties: int = 0
    reactivated_properties: int = 0
    detail_pages_fetched: int = 0
    http_errors: list[dict[str, Any]] = field(default_factory=list)
    parse_errors: list[dict[str, Any]] = field(default_factory=list)
    samples: list[dict[str, Any]] = field(default_factory=list)

    def as_summary(self) -> dict[str, Any]:
        return {
            "provider_key": self.provider_key,
            "mode": self.mode,
            "dry_run": self.dry_run,
            "pages_fetched": self.pages_fetched,
            "listings_seen": self.listings_seen,
            "new_properties": self.new_properties,
            "updated_properties": self.updated_properties,
            "unchanged_properties": self.unchanged_properties,
            "missing_properties": self.missing_properties,
            "removed_properties": self.removed_properties,
            "reactivated_properties": self.reactivated_properties,
            "detail_pages_fetched": self.detail_pages_fetched,
            "http_errors": self.http_errors,
            "parse_errors": self.parse_errors,
            "samples": self.samples,
        }

