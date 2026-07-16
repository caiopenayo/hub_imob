from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import JobLog, Property, PropertyEvent, PropertyPhoto, Source
from scrapers.core.lifecycle import MissingPolicy, status_when_not_seen, status_when_seen
from scrapers.core.normalize import dedupe_urls
from scrapers.core.types import PropertyCandidate, PropertyDetail, SyncStats


@dataclass
class PersistResult:
    property: Property
    created: bool = False
    updated: bool = False
    reactivated: bool = False


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

    async def create_run(self, provider, source: Source, mode: str, search_scope: dict[str, Any] | None) -> JobLog:
        run = JobLog(
            job_name="scraper",
            source_id=source.id,
            provider_key=provider.source_key,
            source_ids=[provider.source_key],
            search_scope=search_scope,
            mode=mode,
            status="running",
            started_at=datetime.utcnow(),
        )
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
            self._apply_candidate(prop, candidate)
            if detail:
                self._apply_detail(prop, detail, now)
            self.session.add(prop)
            await self.session.flush()
            await self.add_event(prop, "CREATED", None, {"external_id": prop.external_id}, run_id, now)
            if detail:
                await self.sync_photos(prop, detail.image_urls)
            return PersistResult(property=prop, created=True)

        old_status = existing.status
        old_price = existing.price
        old_hash = existing.content_hash
        _, reactivated = status_when_seen(old_status)
        self._apply_candidate(existing, candidate)
        existing.source_url = candidate.source_url
        existing.url = candidate.source_url
        existing.last_seen_at = now
        existing.missing_since = None
        existing.removed_at = None
        existing.status = "ACTIVE"
        existing.content_hash = content_hash

        updated = old_hash != content_hash or reactivated
        if detail:
            self._apply_detail(existing, detail, now)
            await self.sync_photos(existing, detail.image_urls)

        self.session.add(existing)
        await self.session.flush()

        if reactivated:
            await self.add_event(existing, "REACTIVATED", {"status": old_status}, {"status": "ACTIVE"}, run_id, now)
        if old_price != existing.price:
            await self.add_event(existing, "PRICE_CHANGED", {"price": old_price}, {"price": existing.price}, run_id, now)
            updated = True
        if old_hash and old_hash != content_hash:
            await self.add_event(existing, "CONTENT_CHANGED", {"content_hash": old_hash}, {"content_hash": content_hash}, run_id, now)
            updated = True

        return PersistResult(property=existing, updated=updated, reactivated=reactivated)

    def _apply_candidate(self, prop: Property, candidate: PropertyCandidate) -> None:
        prop.title = candidate.title
        prop.transaction_type = candidate.transaction_type
        prop.property_type = candidate.property_type
        prop.property_subtype = candidate.property_subtype
        prop.city = candidate.city
        prop.state = candidate.state
        prop.neighborhood = candidate.neighborhood
        prop.address_line = candidate.address_line
        prop.price = candidate.price
        prop.price_currency = candidate.currency or "BRL"
        prop.bedrooms = candidate.bedrooms
        prop.suites = candidate.suites
        prop.bathrooms = candidate.bathrooms
        prop.parking_spaces = candidate.parking_spaces
        prop.area_m2 = candidate.area_m2
        prop.main_image_url = candidate.main_image_url
        metadata = dict(candidate.raw_data or {})
        metadata["tags"] = candidate.tags
        metadata["source"] = candidate.source_key
        if candidate.main_image_url:
            metadata["main_image"] = candidate.main_image_url
        prop.metadata_json = metadata

    def _apply_detail(self, prop: Property, detail: PropertyDetail, now: datetime) -> None:
        prop.description = detail.description
        prop.condominium_fee = detail.condominium_fee
        prop.property_tax = detail.property_tax
        prop.price_per_m2 = detail.price_per_m2
        prop.latitude = detail.latitude
        prop.longitude = detail.longitude
        prop.detail_last_fetched_at = now
        metadata = dict(prop.metadata_json or {})
        metadata.update(
            {
                "images": detail.image_urls,
                "property_features": detail.property_features,
                "condominium_features": detail.condominium_features,
                "nearby_points": detail.nearby_points,
                "video_urls": detail.video_urls,
                "virtual_tour_url": detail.virtual_tour_url,
                "detail_raw_data": detail.raw_data,
            }
        )
        prop.metadata_json = metadata

    async def sync_photos(self, prop: Property, image_urls: list[str]) -> None:
        for position, url in enumerate(dedupe_urls(image_urls), start=1):
            stmt = select(PropertyPhoto).where(PropertyPhoto.property_id == prop.id, PropertyPhoto.source_url == url)
            result = await self.session.execute(stmt)
            photo = result.scalars().first()
            if photo:
                photo.position = position
                self.session.add(photo)
                continue
            self.session.add(PropertyPhoto(property_id=prop.id, source_url=url, position=position))

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
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.utcnow()
        stmt = select(Property).where(Property.source_id == source.id, Property.status != "REMOVED")
        result = await self.session.execute(stmt)
        for prop in result.scalars().all():
            if prop.external_id in seen_external_ids:
                continue
            next_status, changed = status_when_not_seen(prop.status, prop.missing_since, now, True, policy)
            if not changed or not next_status:
                continue
            old_status = prop.status
            prop.status = next_status
            if next_status == "MISSING":
                prop.missing_since = prop.missing_since or now
                stats.missing_properties += 1
                await self.add_event(prop, "MARKED_MISSING", {"status": old_status}, {"status": next_status}, run_id, now)
            elif next_status == "REMOVED":
                prop.removed_at = now
                stats.removed_properties += 1
                await self.add_event(prop, "REMOVED", {"status": old_status}, {"status": next_status}, run_id, now)
            self.session.add(prop)


def detail_is_stale(prop: Property | None, content_hash: str, ttl_hours: int, now: datetime | None = None) -> bool:
    if prop is None:
        return True
    if prop.detail_last_fetched_at is None:
        return True
    if prop.content_hash != content_hash:
        return True
    now = now or datetime.utcnow()
    return now - prop.detail_last_fetched_at >= timedelta(hours=ttl_hours)

