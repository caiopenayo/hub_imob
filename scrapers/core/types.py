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
class PropertyOfferCandidate:
    purpose: str
    price: Decimal | None = None
    currency: str | None = "BRL"
    raw_label: str | None = None
    source_scope: dict[str, Any] | None = None
    content_hash: str | None = None


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
    offers: list[PropertyOfferCandidate] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    raw_data: dict[str, Any] = field(default_factory=dict)
    discovered_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PropertyDetail:
    external_id: str
    title: str | None = None
    canonical_url: str | None = None
    main_image_url: str | None = None
    price: Decimal | None = None
    property_type: str | None = None
    property_subtype: str | None = None
    neighborhood: str | None = None
    address_line: str | None = None
    city: str | None = None
    state: str | None = None
    bedrooms: int | None = None
    suites: int | None = None
    bathrooms: int | None = None
    parking_spaces: int | None = None
    area_m2: Decimal | None = None
    description: str | None = None
    condominium_fee: Decimal | None = None
    property_tax: Decimal | None = None
    price_per_m2: Decimal | None = None
    image_urls: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    property_features: list[str] = field(default_factory=list)
    condominium_description: str | None = None
    condominium_features: list[str] = field(default_factory=list)
    nearby_points: list[dict[str, Any]] = field(default_factory=list)
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    offers: list[PropertyOfferCandidate] = field(default_factory=list)
    video_urls: list[str] = field(default_factory=list)
    virtual_tour_url: str | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ListingPage:
    candidates: list[PropertyCandidate] = field(default_factory=list)
    next_page: int | None = None
    next_url: str | None = None
    is_complete: bool = True
    raw_cards_count: int = 0
    invalid_cards_count: int = 0
    reported_total: int | None = None
    canonical_url: str | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)


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
    reported_total: int | None = None
    unique_external_ids: int = 0
    offers_created: int = 0
    offers_updated: int = 0
    offers_unchanged: int = 0
    missing_offers: int = 0
    removed_offers: int = 0
    reactivated_offers: int = 0
    photos_created: int = 0
    photos_updated: int = 0
    photos_unchanged: int = 0
    photos_inactivated: int = 0
    sale_offers_seen: int = 0
    rent_offers_seen: int = 0
    completed: bool = True
    stopped_reason: str | None = None
    cards_seen: int = 0
    invalid_cards: int = 0
    duration_seconds: float | None = None
    pages_per_second: float | None = None
    requests_total: int = 0
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
            "reported_total": self.reported_total,
            "unique_external_ids": self.unique_external_ids,
            "offers_created": self.offers_created,
            "offers_updated": self.offers_updated,
            "offers_unchanged": self.offers_unchanged,
            "missing_offers": self.missing_offers,
            "removed_offers": self.removed_offers,
            "reactivated_offers": self.reactivated_offers,
            "photos_created": self.photos_created,
            "photos_updated": self.photos_updated,
            "photos_unchanged": self.photos_unchanged,
            "photos_inactivated": self.photos_inactivated,
            "sale_offers_seen": self.sale_offers_seen,
            "rent_offers_seen": self.rent_offers_seen,
            "completed": self.completed,
            "stopped_reason": self.stopped_reason,
            "cards_seen": self.cards_seen,
            "invalid_cards": self.invalid_cards,
            "valid_cards_ratio": (
                (self.cards_seen - self.invalid_cards) / self.cards_seen if self.cards_seen else None
            ),
            "duration_seconds": self.duration_seconds,
            "pages_per_second": self.pages_per_second,
            "requests_total": self.requests_total,
            "http_errors": self.http_errors,
            "parse_errors": self.parse_errors,
            "samples": self.samples,
        }
