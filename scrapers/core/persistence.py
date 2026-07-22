from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import JobLog, Property, PropertyEvent, PropertyOffer, PropertyPhoto, Source
from scrapers.core.lifecycle import MissingPolicy, status_when_not_seen, status_when_seen
from scrapers.core.normalize import dedupe_tags, dedupe_urls, stable_content_hash
from scrapers.core.types import PropertyCandidate, PropertyDetail, PropertyOfferCandidate, SyncStats


@dataclass
class PersistResult:
    property: Property
    created: bool = False
    updated: bool = False
    reactivated: bool = False
    offers_created: int = 0
    offers_updated: int = 0
    offers_unchanged: int = 0
    offers_reactivated: int = 0
    photos_created: int = 0
    photos_updated: int = 0
    photos_unchanged: int = 0
    photos_inactivated: int = 0


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


class PropertyRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def ensure_source(self, provider) -> Source:
        stmt = select(Source).where(Source.key == provider.source_key)
        result = await self.session.execute(stmt)
        source = result.scalars().first()
        if source:
            return source

        source = Source(
            key=provider.source_key,
            name=provider.source_name,
            base_url=provider.base_url,
            notes="Created by shared scraper framework.",
            enabled=True,
        )
        self.session.add(source)
        await self.session.flush()
        return source

    async def get_existing(self, source_id, external_id: str) -> Property | None:
        stmt = select(Property).where(Property.source_id == source_id, Property.external_id == external_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_run(self, run_id) -> JobLog | None:
        stmt = select(JobLog).where(JobLog.id == run_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create_run(self, provider, source: Source, mode: str, search_scope: dict[str, Any] | None) -> JobLog:
        run = self.build_run(provider, source, mode, search_scope)
        self.session.add(run)
        await self.session.flush()
        return run

    def build_run(self, provider, source: Source, mode: str, search_scope: dict[str, Any] | None) -> JobLog:
        return JobLog(
            job_name="scraper",
            source_id=source.id,
            provider_key=provider.source_key,
            source_ids=[provider.source_key],
            search_scope=search_scope,
            mode=mode,
            status="running",
            started_at=datetime.utcnow(),
        )

    async def prepare_existing_run(
        self,
        run: JobLog,
        provider,
        source: Source,
        mode: str,
        search_scope: dict[str, Any] | None,
    ) -> JobLog:
        run.job_name = "scraper"
        run.source_id = source.id
        run.provider_key = provider.source_key
        run.source_ids = [provider.source_key]
        run.search_scope = search_scope
        run.mode = mode
        run.status = "running"
        run.started_at = run.started_at or datetime.utcnow()
        run.finished_at = None
        run.error = None
        self.session.add(run)
        await self.session.flush()
        return run

    async def finish_run(self, run: JobLog, status: str, stats: SyncStats, error: str | None = None) -> None:
        run.status = status
        run.finished_at = datetime.utcnow()
        run.pages_fetched = stats.pages_fetched
        run.listings_seen = stats.listings_seen
        run.new_properties = stats.new_properties
        run.updated_properties = stats.updated_properties
        run.unchanged_properties = stats.unchanged_properties
        run.missing_properties = stats.missing_properties
        run.removed_properties = stats.removed_properties
        run.reactivated_properties = stats.reactivated_properties
        run.detail_pages_fetched = stats.detail_pages_fetched
        run.http_errors = stats.http_errors
        run.parse_errors = stats.parse_errors
        run.summary = stats.as_summary()
        run.error = error
        self.session.add(run)

    async def upsert_property(
        self,
        source: Source,
        candidate: PropertyCandidate,
        content_hash: str,
        detail: PropertyDetail | None,
        run_id=None,
        now: datetime | None = None,
    ) -> PersistResult:
        now = now or datetime.utcnow()
        offers = self._offers_for_persistence(candidate, detail)
        has_offers = bool(offers)
        search_scope = candidate.raw_data.get("search_scope") if isinstance(candidate.raw_data, dict) else None
        scope_hash = candidate.raw_data.get("scope_hash") if isinstance(candidate.raw_data, dict) else None
        existing = await self.get_existing(source.id, candidate.external_id)
        if not existing:
            prop = Property(
                external_id=candidate.external_id,
                source_id=source.id,
                source_url=candidate.source_url,
                url=candidate.source_url,
                first_seen_at=now,
                last_seen_at=now,
                status="ACTIVE",
                content_hash=content_hash,
            )
            self._apply_candidate(prop, candidate, preserve_existing=False)
            if detail:
                self._apply_detail(prop, detail, now)
            self.session.add(prop)
            await self.session.flush()
            offer_result = await self.sync_offers(prop, offers, run_id, now, search_scope, scope_hash) if has_offers else {}
            await self.add_event(
                prop,
                "CREATED",
                None,
                {
                    "external_id": prop.external_id,
                    "price": prop.price,
                    "offers": self._offer_event_payloads(prop, offers),
                },
                run_id,
                now,
            )
            photo_result = await self._sync_property_photos(prop, candidate, detail, allow_listing_gallery=True)
            return PersistResult(
                property=prop,
                created=True,
                offers_created=offer_result.get("created", 0),
                offers_updated=offer_result.get("updated", 0),
                offers_unchanged=offer_result.get("unchanged", 0),
                offers_reactivated=offer_result.get("reactivated", 0),
                photos_created=photo_result.get("created", 0),
                photos_updated=photo_result.get("updated", 0),
                photos_unchanged=photo_result.get("unchanged", 0),
                photos_inactivated=photo_result.get("inactivated", 0),
            )

        old_status = existing.status
        old_price = existing.price
        old_hash = existing.content_hash
        old_snapshot = self._content_snapshot(existing)
        _, reactivated = status_when_seen(old_status)
        self._apply_candidate(existing, candidate, preserve_existing=True)
        existing.source_url = candidate.source_url
        existing.url = candidate.source_url
        existing.last_seen_at = now
        existing.missing_since = None
        existing.removed_at = None
        existing.status = "ACTIVE"
        existing.content_hash = content_hash

        updated = old_hash != content_hash or reactivated
        photo_result: dict[str, int] = {}
        if detail:
            self._apply_detail(existing, detail, now)
            photo_result = await self._sync_property_photos(existing, candidate, detail, allow_listing_gallery=False)
        elif not await self._has_photos(existing):
            photo_result = await self._sync_property_photos(existing, candidate, detail, allow_listing_gallery=True)

        self.session.add(existing)
        await self.session.flush()
        offer_result = await self.sync_offers(existing, offers, run_id, now, search_scope, scope_hash) if has_offers else {}

        changed_fields = self._changed_fields(old_snapshot, self._content_snapshot(existing))

        if reactivated:
            await self.add_event(existing, "REACTIVATED", {"status": old_status}, {"status": "ACTIVE"}, run_id, now)
        if old_price != existing.price and not has_offers:
            await self.add_event(existing, "PRICE_CHANGED", {"price": old_price}, {"price": existing.price}, run_id, now)
            updated = True
        if old_hash and old_hash != content_hash and changed_fields:
            await self.add_event(
                existing,
                "CONTENT_CHANGED",
                {"content_hash": old_hash, "fields": {key: value["old"] for key, value in changed_fields.items()}},
                {"content_hash": content_hash, "fields": {key: value["new"] for key, value in changed_fields.items()}},
                run_id,
                now,
            )
            updated = True
        elif old_hash and old_hash != content_hash:
            updated = True
        elif detail and changed_fields:
            await self.add_event(
                existing,
                "CONTENT_CHANGED",
                {"fields": {key: value["old"] for key, value in changed_fields.items()}},
                {"fields": {key: value["new"] for key, value in changed_fields.items()}},
                run_id,
                now,
            )
            updated = True

        if any(offer_result.get(key, 0) for key in ("created", "updated", "reactivated")):
            updated = True

        return PersistResult(
            property=existing,
            updated=updated,
            reactivated=reactivated,
            offers_created=offer_result.get("created", 0),
            offers_updated=offer_result.get("updated", 0),
            offers_unchanged=offer_result.get("unchanged", 0),
            offers_reactivated=offer_result.get("reactivated", 0),
            photos_created=photo_result.get("created", 0),
            photos_updated=photo_result.get("updated", 0),
            photos_unchanged=photo_result.get("unchanged", 0),
            photos_inactivated=photo_result.get("inactivated", 0),
        )

    def _apply_candidate(self, prop: Property, candidate: PropertyCandidate, preserve_existing: bool = False) -> None:
        def assign(name: str, value: Any) -> None:
            if preserve_existing and value is None:
                return
            setattr(prop, name, value)

        assign("title", candidate.title)
        assign("transaction_type", candidate.transaction_type)
        assign("property_type", candidate.property_type)
        assign("property_subtype", candidate.property_subtype)
        assign("city", candidate.city)
        assign("state", candidate.state)
        assign("neighborhood", candidate.neighborhood)
        assign("address_line", candidate.address_line)
        assign("price", candidate.price)
        prop.price_currency = candidate.currency or prop.price_currency or "BRL"
        assign("bedrooms", candidate.bedrooms)
        assign("suites", candidate.suites)
        assign("bathrooms", candidate.bathrooms)
        assign("parking_spaces", candidate.parking_spaces)
        assign("area_m2", candidate.area_m2)
        assign("main_image_url", candidate.main_image_url)
        metadata = dict(prop.metadata_json or {})
        metadata.update(candidate.raw_data or {})
        metadata["tags"] = candidate.tags
        metadata["source"] = candidate.source_key
        metadata["missing_count"] = 0
        if candidate.offers:
            metadata["offers"] = [self._offer_dict_for_metadata(offer) for offer in candidate.offers]
        if candidate.main_image_url:
            metadata["main_image"] = candidate.main_image_url
        prop.metadata_json = metadata

    def _apply_detail(self, prop: Property, detail: PropertyDetail, now: datetime) -> None:
        if detail.title:
            prop.title = detail.title
        if detail.price is not None:
            prop.price = detail.price
        if detail.property_type:
            prop.property_type = detail.property_type
        if detail.property_subtype:
            prop.property_subtype = detail.property_subtype
        if detail.neighborhood:
            prop.neighborhood = detail.neighborhood
        if detail.address_line:
            prop.address_line = detail.address_line
        detail_city = getattr(detail, "city", None)
        if detail_city:
            prop.city = detail_city
        detail_state = getattr(detail, "state", None)
        if detail_state:
            prop.state = detail_state
        if detail.bedrooms is not None:
            prop.bedrooms = detail.bedrooms
        if detail.suites is not None:
            prop.suites = detail.suites
        if detail.bathrooms is not None:
            prop.bathrooms = detail.bathrooms
        if detail.parking_spaces is not None:
            prop.parking_spaces = detail.parking_spaces
        if self._has_balcony_feature(detail.property_features):
            prop.balcony = True
        if detail.area_m2 is not None:
            prop.area_m2 = detail.area_m2
        if detail.description:
            prop.description = detail.description
        if detail.condominium_fee is not None:
            prop.condominium_fee = detail.condominium_fee
        if detail.property_tax is not None:
            prop.property_tax = detail.property_tax
        if detail.price_per_m2 is not None:
            prop.price_per_m2 = detail.price_per_m2
        if detail.latitude is not None:
            prop.latitude = detail.latitude
        if detail.longitude is not None:
            prop.longitude = detail.longitude
        if detail.main_image_url:
            prop.main_image_url = detail.main_image_url
        elif detail.image_urls:
            prop.main_image_url = detail.image_urls[0]
        prop.detail_last_fetched_at = now
        metadata = dict(prop.metadata_json or {})
        existing_tags = metadata.get("tags")
        if not isinstance(existing_tags, list):
            existing_tags = []
        metadata["tags"] = dedupe_tags([*existing_tags, *detail.tags])
        if prop.main_image_url:
            metadata["main_image"] = prop.main_image_url
        metadata.update(
            {
                "canonical_url": detail.canonical_url,
                "images": detail.image_urls,
                "property_features": detail.property_features,
                "condominium_description": detail.condominium_description,
                "condominium_features": detail.condominium_features,
                "nearby_points": detail.nearby_points,
                "video_urls": detail.video_urls,
                "virtual_tour_url": detail.virtual_tour_url,
                "detail_raw_data": detail.raw_data,
            }
        )
        prop.metadata_json = metadata

    async def sync_offers(
        self,
        prop: Property,
        offers: list[PropertyOfferCandidate],
        run_id=None,
        now: datetime | None = None,
        search_scope: dict[str, Any] | None = None,
        scope_hash: str | None = None,
    ) -> dict[str, int]:
        now = now or datetime.utcnow()
        result = {"created": 0, "updated": 0, "unchanged": 0, "reactivated": 0}
        normalized_offers = self._normalized_offers(offers)
        if not normalized_offers:
            return result

        stmt = select(PropertyOffer).where(PropertyOffer.property_id == prop.id)
        query_result = await self.session.execute(stmt)
        existing = {offer.purpose: offer for offer in query_result.scalars().all()}

        for incoming in normalized_offers:
            content_hash = self._offer_content_hash(incoming)
            purpose = self._normalize_purpose(incoming.purpose)
            metadata = {
                "raw_label": incoming.raw_label,
                "source_scope": incoming.source_scope or search_scope,
                "scope_hash": scope_hash,
            }
            offer = existing.get(purpose)
            if not offer:
                self.session.add(
                    PropertyOffer(
                        property_id=prop.id,
                        purpose=purpose,
                        price=incoming.price,
                        currency=incoming.currency or "BRL",
                        status="ACTIVE",
                        content_hash=content_hash,
                        first_seen_at=now,
                        last_seen_at=now,
                        metadata_json=metadata,
                    )
                )
                result["created"] += 1
                continue

            old_status = offer.status
            old_price = offer.price
            old_hash = offer.content_hash
            _, reactivated = status_when_seen(old_status)
            offer.price = incoming.price
            offer.currency = incoming.currency or offer.currency or "BRL"
            offer.status = "ACTIVE"
            offer.content_hash = content_hash
            offer.last_seen_at = now
            offer.missing_since = None
            offer.removed_at = None
            offer.metadata_json = {**(offer.metadata_json or {}), **metadata, "missing_count": 0}
            self.session.add(offer)

            changed = False
            if reactivated:
                result["reactivated"] += 1
                await self.add_event(
                    prop,
                    "REACTIVATED",
                    {"entity": "offer", "purpose": purpose, "status": old_status},
                    {"entity": "offer", "purpose": purpose, "status": "ACTIVE"},
                    run_id,
                    now,
                )
                changed = True
            if old_price != offer.price:
                await self.add_event(
                    prop,
                    "PRICE_CHANGED",
                    {"entity": "offer", "purpose": purpose, "price": old_price},
                    {"entity": "offer", "purpose": purpose, "price": offer.price},
                    run_id,
                    now,
                )
                changed = True
            elif old_hash and old_hash != content_hash:
                await self.add_event(
                    prop,
                    "CONTENT_CHANGED",
                    {"entity": "offer", "purpose": purpose, "content_hash": old_hash},
                    {"entity": "offer", "purpose": purpose, "content_hash": content_hash},
                    run_id,
                    now,
                )
                changed = True

            if changed:
                result["updated"] += 1
            else:
                result["unchanged"] += 1

        await self._sync_property_status_from_offers(prop, now)
        return result

    def _offers_for_persistence(
        self,
        candidate: PropertyCandidate,
        detail: PropertyDetail | None,
    ) -> list[PropertyOfferCandidate]:
        if detail and detail.offers:
            return detail.offers
        return candidate.offers

    def _normalized_offers(self, offers: list[PropertyOfferCandidate]) -> list[PropertyOfferCandidate]:
        by_purpose: dict[str, PropertyOfferCandidate] = {}
        for offer in offers:
            purpose = self._normalize_purpose(offer.purpose)
            if purpose not in {"SALE", "RENT"}:
                continue
            offer.purpose = purpose
            offer.currency = offer.currency or "BRL"
            offer.content_hash = offer.content_hash or self._offer_content_hash(offer)
            by_purpose[purpose] = offer
        return [by_purpose[key] for key in sorted(by_purpose)]

    def _offer_content_hash(self, offer: PropertyOfferCandidate) -> str:
        return stable_content_hash(
            {
                "purpose": self._normalize_purpose(offer.purpose),
                "price": offer.price,
                "currency": offer.currency or "BRL",
            }
        )

    def _normalize_purpose(self, value: str | None) -> str:
        normalized = (value or "").strip().lower()
        if normalized in {"sale", "venda"}:
            return "SALE"
        if normalized in {"rent", "locacao", "locação", "aluguel"}:
            return "RENT"
        return normalized.upper()

    def _offer_event_payloads(
        self,
        prop: Property,
        offers: list[PropertyOfferCandidate],
    ) -> list[dict[str, Any]]:
        return [
            {
                "purpose": self._normalize_purpose(offer.purpose),
                "price": offer.price,
                "currency": offer.currency or prop.price_currency or "BRL",
            }
            for offer in self._normalized_offers(offers)
        ]

    def _offer_dict_for_metadata(self, offer: PropertyOfferCandidate) -> dict[str, Any]:
        return _json_safe(
            {
                "purpose": self._normalize_purpose(offer.purpose),
                "price": offer.price,
                "currency": offer.currency,
                "raw_label": offer.raw_label,
                "source_scope": offer.source_scope,
                "content_hash": offer.content_hash,
            }
        )

    async def _sync_property_status_from_offers(self, prop: Property, now: datetime) -> None:
        stmt = select(PropertyOffer).where(PropertyOffer.property_id == prop.id)
        result = await self.session.execute(stmt)
        offers = result.scalars().all()
        if not offers:
            return

        statuses = {(offer.status or "ACTIVE").upper() for offer in offers}
        old_status = (prop.status or "ACTIVE").upper()
        if "ACTIVE" in statuses:
            prop.status = "ACTIVE"
            prop.missing_since = None
            prop.removed_at = None
        elif statuses == {"REMOVED"}:
            prop.status = "REMOVED"
            prop.removed_at = prop.removed_at or now
        else:
            prop.status = "MISSING"
            prop.missing_since = prop.missing_since or now
        if old_status != prop.status:
            self.session.add(prop)

    async def _sync_property_photos(
        self,
        prop: Property,
        candidate: PropertyCandidate,
        detail: PropertyDetail | None,
        allow_listing_gallery: bool,
    ) -> dict[str, int]:
        urls = detail.image_urls if detail and detail.image_urls else []
        if not urls and allow_listing_gallery:
            urls = self._candidate_image_urls(candidate)
        if not urls:
            return {}
        return await self.sync_photos(prop, urls)

    def _candidate_image_urls(self, candidate: PropertyCandidate) -> list[str]:
        raw_data = candidate.raw_data if isinstance(candidate.raw_data, dict) else {}
        values = raw_data.get("listing_image_urls") or raw_data.get("image_urls") or []
        if not isinstance(values, list):
            values = []
        return dedupe_urls([candidate.main_image_url, *values])

    async def _has_photos(self, prop: Property) -> bool:
        stmt = select(PropertyPhoto).where(PropertyPhoto.property_id == prop.id).limit(1)
        result = await self.session.execute(stmt)
        return result.scalars().first() is not None

    async def sync_photos(self, prop: Property, image_urls: list[str]) -> dict[str, int]:
        urls = dedupe_urls(image_urls)
        seen_urls = set(urls)
        stmt = select(PropertyPhoto).where(PropertyPhoto.property_id == prop.id)
        result = await self.session.execute(stmt)
        existing = {photo.source_url: photo for photo in result.scalars().all()}
        counts = {"created": 0, "updated": 0, "unchanged": 0, "inactivated": 0}

        for position, url in enumerate(urls, start=1):
            photo = existing.get(url)
            if photo:
                changed = photo.position != position
                photo.position = position
                if hasattr(photo, "is_active"):
                    changed = changed or photo.is_active is False
                    photo.is_active = True
                if hasattr(photo, "removed_at"):
                    changed = changed or photo.removed_at is not None
                    photo.removed_at = None
                self.session.add(photo)
                counts["updated" if changed else "unchanged"] += 1
                continue
            self.session.add(PropertyPhoto(property_id=prop.id, source_url=url, position=position, is_active=True))
            counts["created"] += 1

        now = datetime.utcnow()
        for url, photo in existing.items():
            if url in seen_urls:
                continue
            changed = False
            if hasattr(photo, "is_active"):
                changed = changed or photo.is_active is True
                photo.is_active = False
            if hasattr(photo, "removed_at") and photo.removed_at is None:
                photo.removed_at = now
                changed = True
            self.session.add(photo)
            if changed:
                counts["inactivated"] += 1
        return counts

    async def add_event(
        self,
        prop: Property,
        event_type: str,
        old_value: dict[str, Any] | None,
        new_value: dict[str, Any] | None,
        run_id=None,
        now: datetime | None = None,
    ) -> None:
        self.session.add(
            PropertyEvent(
                property_id=prop.id,
                event_type=event_type,
                old_value=_json_safe(old_value),
                new_value=_json_safe(new_value),
                crawl_run_id=run_id,
                detected_at=now or datetime.utcnow(),
            )
        )

    async def reconcile_missing(
        self,
        source: Source,
        seen_external_ids: set[str],
        run_id,
        stats: SyncStats,
        policy: MissingPolicy,
        scope_hash: str | None = None,
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.utcnow()
        stmt = select(Property).where(Property.source_id == source.id, Property.status != "REMOVED")
        result = await self.session.execute(stmt)
        for prop in result.scalars().all():
            if prop.external_id in seen_external_ids:
                continue
            metadata = dict(prop.metadata_json or {})
            if scope_hash and metadata.get("scope_hash") != scope_hash:
                continue
            missing_count = int(metadata.get("missing_count") or 0) + 1
            metadata["missing_count"] = missing_count
            next_status, changed = status_when_not_seen(prop.status, prop.missing_since, now, True, policy)
            if prop.status == "MISSING" and missing_count >= policy.missing_threshold:
                next_status, changed = "REMOVED", True
            if not changed or not next_status:
                prop.metadata_json = metadata
                self.session.add(prop)
                continue
            old_status = prop.status
            prop.status = next_status
            prop.metadata_json = metadata
            if next_status == "MISSING":
                prop.missing_since = prop.missing_since or now
                stats.missing_properties += 1
                await self.add_event(prop, "MARKED_MISSING", {"status": old_status}, {"status": next_status}, run_id, now)
            elif next_status == "REMOVED":
                prop.removed_at = now
                stats.removed_properties += 1
                await self.add_event(prop, "REMOVED", {"status": old_status}, {"status": next_status}, run_id, now)
            self.session.add(prop)

    async def reconcile_missing_offers(
        self,
        source: Source,
        seen_offer_keys: set[tuple[str, str]],
        purposes: set[str],
        run_id,
        stats: SyncStats,
        policy: MissingPolicy,
        scope_hash: str | None = None,
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.utcnow()
        normalized_purposes = {self._normalize_purpose(purpose) for purpose in purposes}
        if not normalized_purposes:
            return

        stmt = (
            select(PropertyOffer, Property)
            .join(Property, PropertyOffer.property_id == Property.id)
            .where(Property.source_id == source.id, PropertyOffer.purpose.in_(normalized_purposes))
        )
        result = await self.session.execute(stmt)
        for offer, prop in result.all():
            if (prop.external_id, offer.purpose) in seen_offer_keys:
                continue
            metadata = dict(offer.metadata_json or {})
            if scope_hash and metadata.get("scope_hash") != scope_hash:
                continue
            missing_count = int(metadata.get("missing_count") or 0) + 1
            metadata["missing_count"] = missing_count
            next_status, changed = status_when_not_seen(offer.status, offer.missing_since, now, True, policy)
            if offer.status == "MISSING" and missing_count >= policy.missing_threshold:
                next_status, changed = "REMOVED", True
            if not changed or not next_status:
                offer.metadata_json = metadata
                self.session.add(offer)
                continue

            old_status = offer.status
            offer.status = next_status
            offer.metadata_json = metadata
            if next_status == "MISSING":
                offer.missing_since = offer.missing_since or now
                stats.missing_offers += 1
                await self.add_event(
                    prop,
                    "MARKED_MISSING",
                    {"entity": "offer", "purpose": offer.purpose, "status": old_status},
                    {"entity": "offer", "purpose": offer.purpose, "status": next_status},
                    run_id,
                    now,
                )
            elif next_status == "REMOVED":
                offer.removed_at = now
                stats.removed_offers += 1
                await self.add_event(
                    prop,
                    "REMOVED",
                    {"entity": "offer", "purpose": offer.purpose, "status": old_status},
                    {"entity": "offer", "purpose": offer.purpose, "status": next_status},
                    run_id,
                    now,
                )
            self.session.add(offer)
            old_prop_status = prop.status
            await self._sync_property_status_from_offers(prop, now)
            if old_prop_status != prop.status:
                if prop.status == "MISSING":
                    stats.missing_properties += 1
                elif prop.status == "REMOVED":
                    stats.removed_properties += 1

    async def last_successful_full_count(self, source: Source, search_scope: dict[str, Any] | None) -> int | None:
        stmt = (
            select(JobLog)
            .where(JobLog.source_id == source.id, JobLog.mode == "full", JobLog.status == "success")
            .order_by(JobLog.finished_at.desc().nullslast())
            .limit(20)
        )
        result = await self.session.execute(stmt)
        for run in result.scalars().all():
            if (run.search_scope or {}) == (search_scope or {}):
                summary = run.summary or {}
                listings_seen = summary.get("listings_seen") or run.listings_seen
                return int(listings_seen or 0)
        return None

    def _content_snapshot(self, prop: Property) -> dict[str, Any]:
        metadata = prop.metadata_json or {}
        return _json_safe(
            {
                "title": prop.title,
                "description": prop.description,
                "transaction_type": prop.transaction_type,
                "property_type": prop.property_type,
                "property_subtype": prop.property_subtype,
                "condominium_fee": prop.condominium_fee,
                "property_tax": prop.property_tax,
                "price_per_m2": prop.price_per_m2,
                "address_line": prop.address_line,
                "city": prop.city,
                "state": prop.state,
                "neighborhood": prop.neighborhood,
                "bedrooms": prop.bedrooms,
                "suites": prop.suites,
                "bathrooms": prop.bathrooms,
                "parking_spaces": prop.parking_spaces,
                "balcony": prop.balcony,
                "area_m2": prop.area_m2,
                "main_image_url": prop.main_image_url,
                "latitude": prop.latitude,
                "longitude": prop.longitude,
                "detail_hash": (metadata.get("detail_raw_data") or {}).get("detail_hash"),
                "tags": sorted(metadata.get("tags") or []),
            }
        )

    def _changed_fields(self, old: dict[str, Any], new: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            key: {"old": old.get(key), "new": new.get(key)}
            for key in sorted(set(old) | set(new))
            if old.get(key) != new.get(key)
        }

    @staticmethod
    def _has_balcony_feature(features: list[str] | None) -> bool:
        text = " ".join(features or []).casefold()
        return any(token in text for token in ("varanda", "sacada", "terraço", "terraco"))


def detail_is_stale(prop: Property | None, content_hash: str, ttl_hours: int, now: datetime | None = None) -> bool:
    if prop is None:
        return True
    if prop.detail_last_fetched_at is None:
        return True
    if prop.content_hash != content_hash:
        return True
    now = now or datetime.utcnow()
    return now - prop.detail_last_fetched_at >= timedelta(hours=ttl_hours)
