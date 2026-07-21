from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .http import ScraperHTTPError, SharedScraperHTTPClient
from .lifecycle import MissingPolicy
from .normalize import candidate_hash_payload, stable_content_hash
from .persistence import PropertyRepository, detail_is_stale
from .providers import RealEstateProvider
from .settings import ScraperSettings
from .types import PropertyCandidate, PropertyDetail, SyncMode, SyncStats

logger = logging.getLogger(__name__)


class SyncEngine:
    def __init__(
        self,
        provider: RealEstateProvider,
        settings: ScraperSettings,
        session: AsyncSession | None = None,
        http_client: SharedScraperHTTPClient | None = None,
    ):
        self.provider = provider
        self.settings = settings
        self.session = session
        self.http_client = http_client

    async def run(
        self,
        mode: SyncMode = "delta",
        search_scope: dict[str, Any] | None = None,
        dry_run: bool | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        max_details: int | None = None,
        run_id=None,
    ) -> SyncStats:
        started_at = datetime.utcnow()
        dry_run = self.settings.dry_run if dry_run is None else dry_run
        stats = SyncStats(provider_key=self.provider.source_key, mode=mode, dry_run=dry_run)
        search_scope = search_scope or self.provider.default_search_scope
        scope_hash = stable_content_hash(search_scope or {})
        run = None
        source = None
        repo = PropertyRepository(self.session) if self.session is not None else None

        if not dry_run:
            if repo is None:
                raise RuntimeError("A database session is required when dry_run=False")
            source = await repo.ensure_source(self.provider)
            if source.enabled is False:
                return stats
            if run_id:
                run = await repo.get_run(run_id)
                if run is None:
                    raise RuntimeError(f"crawl run not found: {run_id}")
                run = await repo.prepare_existing_run(run, self.provider, source, mode, search_scope)
            else:
                run = await repo.create_run(self.provider, source, mode, search_scope)

        logger.info(
            "sync_run_started",
            extra={
                "provider": self.provider.source_key,
                "run_id": str(run.id) if run else None,
                "source_id": str(source.id) if source else None,
                "mode": mode,
                "dry_run": dry_run,
            },
        )

        try:
            async with self._client_context() as client:
                candidates = await self._discover(client, stats, search_scope, limit, max_pages, mode)
                unique_candidates = self._dedupe(candidates)
                for candidate in unique_candidates:
                    candidate.raw_data = dict(candidate.raw_data or {})
                    candidate.raw_data["search_scope"] = search_scope
                    candidate.raw_data["scope_hash"] = scope_hash
                    self._filter_candidate_offers(candidate, search_scope)
                stats.listings_seen = len(unique_candidates)
                stats.unique_external_ids = len(unique_candidates)

                if dry_run:
                    for candidate in unique_candidates:
                        self._count_seen_offers(stats, candidate)
                    stats.samples = await self._dry_run_samples(client, unique_candidates, max_details, stats)
                    self._finish_stats(stats, started_at)
                    return stats

                assert repo is not None
                assert source is not None
                seen_external_ids = set()
                seen_offer_keys: set[tuple[str, str]] = set()
                details_fetched = 0
                for candidate in unique_candidates:
                    seen_external_ids.add(candidate.external_id)
                    self._count_seen_offers(stats, candidate)
                    content_hash = stable_content_hash(candidate_hash_payload(candidate))
                    existing = await repo.get_existing(source.id, candidate.external_id)
                    can_fetch_detail = max_details is None or details_fetched < max_details
                    detail = None
                    if can_fetch_detail:
                        before = stats.detail_pages_fetched
                        detail = await self._maybe_fetch_detail(client, candidate, existing, content_hash, mode, stats)
                        if stats.detail_pages_fetched > before:
                            details_fetched += 1
                        self._filter_detail_offers(detail, search_scope)
                    result = await repo.upsert_property(
                        source,
                        candidate,
                        content_hash,
                        detail,
                        run_id=run.id if run else None,
                    )
                    seen_offer_keys.update(self._candidate_offer_keys(candidate, detail))
                    stats.offers_created += result.offers_created
                    stats.offers_updated += result.offers_updated
                    stats.offers_unchanged += result.offers_unchanged
                    stats.reactivated_offers += result.offers_reactivated
                    stats.photos_created += result.photos_created
                    stats.photos_updated += result.photos_updated
                    stats.photos_unchanged += result.photos_unchanged
                    stats.photos_inactivated += result.photos_inactivated
                    if result.created:
                        stats.new_properties += 1
                        action = "created"
                    elif result.reactivated:
                        stats.reactivated_properties += 1
                        action = "reactivated"
                    elif result.updated:
                        stats.updated_properties += 1
                        action = "updated"
                    else:
                        stats.unchanged_properties += 1
                        action = "unchanged"
                    logger.info(
                        "property_upserted",
                        extra={
                            "provider": self.provider.source_key,
                            "run_id": str(run.id) if run else None,
                            "source_id": str(source.id),
                            "external_id": candidate.external_id,
                            "purpose": (search_scope or {}).get("purpose"),
                            "action": action,
                            "offers_created": result.offers_created,
                            "offers_updated": result.offers_updated,
                            "offers_reactivated": result.offers_reactivated,
                        },
                    )

                run_status = await self._classify_run_status(
                    repo,
                    source,
                    stats,
                    mode,
                    search_scope,
                    max_pages,
                )

                if mode == "full" and run_status == "success":
                    policy = MissingPolicy(
                        missing_threshold=self.settings.missing_threshold,
                        removal_after_hours=self.settings.removal_after_hours,
                    )
                    if getattr(self.provider, "uses_offers", False):
                        await repo.reconcile_missing_offers(
                            source,
                            seen_offer_keys,
                            self._scope_purposes(search_scope),
                            run.id if run else None,
                            stats,
                            policy,
                            scope_hash=scope_hash,
                        )
                    else:
                        await repo.reconcile_missing(
                            source,
                            seen_external_ids,
                            run.id if run else None,
                            stats,
                            policy,
                            scope_hash=scope_hash,
                        )

                self._finish_stats(stats, started_at)
                if run:
                    await repo.finish_run(run, run_status, stats)
                await self.session.commit()
                logger.info(
                    "sync_run_finished",
                    extra={
                        "provider": self.provider.source_key,
                        "run_id": str(run.id) if run else None,
                        "source_id": str(source.id) if source else None,
                        "status": run_status,
                        "listings_seen": stats.listings_seen,
                    },
                )
                return stats
        except Exception as exc:
            self._finish_stats(stats, started_at)
            if run and repo:
                await repo.finish_run(run, "failed", stats, error=str(exc)[:1000])
                await self.session.commit()
            raise

    async def _discover(
        self,
        client: SharedScraperHTTPClient,
        stats: SyncStats,
        search_scope: dict[str, Any],
        limit: int | None,
        max_pages: int | None,
        mode: SyncMode,
    ) -> list[PropertyCandidate]:
        candidates: list[PropertyCandidate] = []
        page = 1
        max_pages = self.settings.max_pages if max_pages is None else max_pages
        seen_external_ids: set[str] = set()
        previous_page_ids: set[str] = set()
        visited_urls: set[str] = set()
        next_url: str | None = None
        stale_pages = 0

        while page and (max_pages <= 0 or page <= max_pages):
            try:
                if next_url:
                    if next_url in visited_urls:
                        stats.completed = False
                        stats.stopped_reason = "repeated_next_url"
                        break
                    visited_urls.add(next_url)
                    html = await self.provider.fetch_listing_url(client, next_url)
                else:
                    request_url = self.provider.build_search_request(page, search_scope).url
                    if request_url in visited_urls:
                        stats.completed = False
                        stats.stopped_reason = "repeated_listing_url"
                        break
                    visited_urls.add(request_url)
                    html = await self.provider.fetch_listing_page(client, page, search_scope)
                stats.pages_fetched += 1
                stats.requests_total += 1
                listing_page = self.provider.parse_listing_page(html, page, search_scope)
                logger.info(
                    "listing_parsed",
                    extra={
                        "provider": self.provider.source_key,
                        "page": page,
                        "purpose": (search_scope or {}).get("purpose"),
                        "cards": len(listing_page.candidates),
                        "raw_cards": listing_page.raw_cards_count,
                        "invalid_cards": listing_page.invalid_cards_count,
                        "reported_total": listing_page.reported_total,
                        "next_url": listing_page.next_url,
                    },
                )
                if listing_page.reported_total is not None and stats.reported_total is None:
                    stats.reported_total = listing_page.reported_total
                stats.cards_seen += listing_page.raw_cards_count or len(listing_page.candidates)
                stats.invalid_cards += listing_page.invalid_cards_count
                if self._invalid_card_rate(stats) > self.settings.max_invalid_card_rate:
                    stats.completed = False
                    stats.stopped_reason = "invalid_card_rate"
                    break
                page_ids = {candidate.external_id for candidate in listing_page.candidates if candidate.external_id}
                if not page_ids:
                    if listing_page.reported_total and listing_page.reported_total > 0:
                        stats.completed = False
                        stats.stopped_reason = "reported_total_without_cards"
                        break
                    stats.stopped_reason = "no_cards"
                    break
                if page > 1 and page_ids == previous_page_ids:
                    if mode == "full":
                        stats.completed = False
                    stats.stopped_reason = "repeated_page"
                    break
                new_page_candidates = [
                    candidate for candidate in listing_page.candidates if candidate.external_id not in seen_external_ids
                ]
                if page > 1 and not new_page_candidates:
                    stale_pages += 1
                    if mode == "delta" and stale_pages < max(1, self.settings.delta_stale_pages):
                        next_url = listing_page.next_url
                        page = page + 1 if next_url else listing_page.next_page
                        previous_page_ids = page_ids
                        continue
                    if mode == "full":
                        stats.completed = False
                    stats.stopped_reason = "no_new_external_ids"
                    break
                stale_pages = 0
                for candidate in listing_page.candidates:
                    if candidate.external_id in seen_external_ids:
                        continue
                    candidates.append(self.provider.normalize_listing(candidate))
                    seen_external_ids.add(candidate.external_id)
                    if limit and len(candidates) >= limit:
                        stats.stopped_reason = "limit"
                        return candidates
                previous_page_ids = page_ids
                next_url = listing_page.next_url
                page = page + 1 if next_url else listing_page.next_page
            except ScraperHTTPError as exc:
                if exc.status_code == 404 and page > 1:
                    stats.stopped_reason = "http_404"
                    break
                stats.http_errors.append({"page": page, "status_code": exc.status_code, "url": exc.url})
                stats.completed = False
                stats.stopped_reason = f"http_{exc.status_code or 'error'}"
                break
            except Exception as exc:
                stats.parse_errors.append({"page": page, "error": str(exc)[:500]})
                stats.completed = False
                stats.stopped_reason = "parse_error"
                break
        else:
            if max_pages > 0:
                stats.stopped_reason = "max_pages"
                stats.completed = False

        return candidates

    async def _dry_run_samples(
        self,
        client: SharedScraperHTTPClient,
        candidates: list[PropertyCandidate],
        max_details: int | None,
        stats: SyncStats,
    ) -> list[dict[str, Any]]:
        samples = [self._sample(candidate) for candidate in candidates[:5]]
        detail_limit = max(0, max_details or 0)
        if detail_limit <= 0:
            return samples

        details_by_id: dict[str, dict[str, Any]] = {}
        for candidate in candidates[:detail_limit]:
            detail = await self._maybe_fetch_detail(client, candidate, None, "", "delta", stats)
            if detail is None:
                continue
            details_by_id[candidate.external_id] = self._detail_sample(detail)

        for sample in samples:
            detail_sample = details_by_id.get(sample["external_id"])
            if detail_sample:
                sample["detail"] = detail_sample
        return samples

    async def _maybe_fetch_detail(
        self,
        client: SharedScraperHTTPClient,
        candidate: PropertyCandidate,
        existing,
        content_hash: str,
        mode: SyncMode,
        stats: SyncStats,
    ) -> PropertyDetail | None:
        should_fetch = (
            mode == "full"
            or existing is None
            or detail_is_stale(existing, content_hash, self.settings.detail_ttl_hours)
        )
        if not should_fetch:
            return None
        try:
            html = await self.provider.fetch_property_detail(client, candidate)
            stats.detail_pages_fetched += 1
            stats.requests_total += 1
            detail = self.provider.parse_property_detail(html, candidate)
            logger.info(
                "detail_fetched",
                extra={
                    "provider": self.provider.source_key,
                    "external_id": candidate.external_id,
                    "purpose": (candidate.raw_data or {}).get("search_scope", {}).get("purpose"),
                },
            )
            return self.provider.normalize_detail(candidate, detail)
        except ScraperHTTPError as exc:
            stats.http_errors.append({"external_id": candidate.external_id, "status_code": exc.status_code, "url": exc.url})
        except Exception as exc:
            stats.parse_errors.append({"external_id": candidate.external_id, "error": str(exc)[:500]})
        return None

    def _dedupe(self, candidates: list[PropertyCandidate]) -> list[PropertyCandidate]:
        seen: set[str] = set()
        unique: list[PropertyCandidate] = []
        for candidate in candidates:
            if candidate.external_id in seen:
                continue
            seen.add(candidate.external_id)
            unique.append(candidate)
        return unique

    def _candidate_offer_keys(
        self,
        candidate: PropertyCandidate,
        detail: PropertyDetail | None,
    ) -> set[tuple[str, str]]:
        offers = detail.offers if detail and detail.offers else candidate.offers
        return {
            (candidate.external_id, self._normalize_purpose(offer.purpose))
            for offer in offers
            if self._normalize_purpose(offer.purpose) in {"SALE", "RENT"}
        }

    def _count_seen_offers(self, stats: SyncStats, candidate: PropertyCandidate) -> None:
        for offer in candidate.offers:
            purpose = self._normalize_purpose(offer.purpose)
            if purpose == "SALE":
                stats.sale_offers_seen += 1
            elif purpose == "RENT":
                stats.rent_offers_seen += 1

    def _filter_candidate_offers(self, candidate: PropertyCandidate, search_scope: dict[str, Any] | None) -> None:
        allowed = self._sync_offer_purposes(search_scope)
        if not allowed:
            return
        candidate.offers = [
            offer for offer in candidate.offers if self._normalize_purpose(offer.purpose) in allowed
        ]

    def _filter_detail_offers(self, detail: PropertyDetail | None, search_scope: dict[str, Any] | None) -> None:
        allowed = self._sync_offer_purposes(search_scope)
        if not detail or not allowed:
            return
        detail.offers = [
            offer for offer in detail.offers if self._normalize_purpose(offer.purpose) in allowed
        ]

    def _sync_offer_purposes(self, search_scope: dict[str, Any] | None) -> set[str]:
        scope = search_scope or {}
        values = scope.get("sync_offer_purposes")
        if values is None:
            return set()
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            return set()
        return {self._normalize_purpose(value) for value in values if self._normalize_purpose(value) in {"SALE", "RENT"}}

    def _scope_purposes(self, search_scope: dict[str, Any] | None) -> set[str]:
        scope = search_scope or {}
        values = scope.get("purposes") or scope.get("purpose") or "sale"
        if isinstance(values, str):
            values = [values]
        return {self._normalize_purpose(value) for value in values if self._normalize_purpose(value) in {"SALE", "RENT"}}

    def _normalize_purpose(self, value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"sale", "venda"}:
            return "SALE"
        if normalized in {"rent", "locacao", "locação", "aluguel"}:
            return "RENT"
        return normalized.upper()

    def _sample(self, candidate: PropertyCandidate) -> dict[str, Any]:
        return {
            "external_id": candidate.external_id,
            "source_url": candidate.source_url,
            "title": candidate.title,
            "price": str(candidate.price) if candidate.price is not None else None,
            "property_type": candidate.property_type,
            "neighborhood": candidate.neighborhood,
            "address_line": candidate.address_line,
            "area_m2": str(candidate.area_m2) if candidate.area_m2 is not None else None,
            "bedrooms": candidate.bedrooms,
            "suites": candidate.suites,
            "parking_spaces": candidate.parking_spaces,
            "main_image_url": candidate.main_image_url,
            "offers": [
                {
                    "purpose": offer.purpose,
                    "price": str(offer.price) if offer.price is not None else None,
                    "currency": offer.currency,
                    "raw_label": offer.raw_label,
                }
                for offer in getattr(candidate, "offers", []) or []
            ],
            "tags": candidate.tags,
        }

    def _detail_sample(self, detail: PropertyDetail) -> dict[str, Any]:
        return {
            "external_id": detail.external_id,
            "canonical_url": detail.canonical_url,
            "title": detail.title,
            "description": detail.description,
            "price": str(detail.price) if detail.price is not None else None,
            "condominium_fee": str(detail.condominium_fee) if detail.condominium_fee is not None else None,
            "property_tax": str(detail.property_tax) if detail.property_tax is not None else None,
            "price_per_m2": str(detail.price_per_m2) if detail.price_per_m2 is not None else None,
            "image_urls": detail.image_urls,
            "property_features": detail.property_features,
            "condominium_features": detail.condominium_features,
            "nearby_points": detail.nearby_points,
            "latitude": str(detail.latitude) if detail.latitude is not None else None,
            "longitude": str(detail.longitude) if detail.longitude is not None else None,
            "offers": [
                {
                    "purpose": offer.purpose,
                    "price": str(offer.price) if offer.price is not None else None,
                    "currency": offer.currency,
                    "raw_label": offer.raw_label,
                }
                for offer in getattr(detail, "offers", []) or []
            ],
            "video_urls": detail.video_urls,
            "raw_data": detail.raw_data,
        }

    def _client_context(self):
        if self.http_client is not None:
            return self.http_client
        return SharedScraperHTTPClient(self.settings, provider_headers=self.provider.headers)

    async def _classify_run_status(
        self,
        repo: PropertyRepository,
        source,
        stats: SyncStats,
        mode: SyncMode,
        search_scope: dict[str, Any] | None,
        max_pages: int | None,
    ) -> str:
        if not stats.completed or stats.http_errors or stats.parse_errors:
            return "partial"
        if stats.stopped_reason == "max_pages":
            stats.completed = False
            return "partial"
        if mode == "full":
            if stats.stopped_reason in {"max_pages", "limit", "invalid_card_rate"}:
                stats.completed = False
                return "partial"
            if stats.reported_total and stats.listings_seen < stats.reported_total * self.settings.full_min_listing_ratio:
                stats.completed = False
                stats.stopped_reason = "suspicious_reported_total_gap"
                return "partial"
            previous_count = await repo.last_successful_full_count(source, search_scope)
            if previous_count and stats.listings_seen < previous_count * self.settings.full_min_listing_ratio:
                stats.completed = False
                stats.stopped_reason = "suspicious_low_count"
                return "partial"
        return "success"

    def _finish_stats(self, stats: SyncStats, started_at: datetime) -> None:
        duration = max(0.0, (datetime.utcnow() - started_at).total_seconds())
        stats.duration_seconds = round(duration, 6)
        stats.pages_per_second = round(stats.pages_fetched / duration, 6) if duration > 0 else None
        if not stats.requests_total:
            stats.requests_total = stats.pages_fetched + stats.detail_pages_fetched

    def _invalid_card_rate(self, stats: SyncStats) -> float:
        if not stats.cards_seen:
            return 0.0
        return stats.invalid_cards / stats.cards_seen
