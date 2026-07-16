from __future__ import annotations

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
    ) -> SyncStats:
        dry_run = self.settings.dry_run if dry_run is None else dry_run
        stats = SyncStats(provider_key=self.provider.source_key, mode=mode, dry_run=dry_run)
        search_scope = search_scope or self.provider.default_search_scope
        run = None
        source = None
        repo = PropertyRepository(self.session) if self.session is not None else None

        if not dry_run:
            if repo is None:
                raise RuntimeError("A database session is required when dry_run=False")
            source = await repo.ensure_source(self.provider)
            if source.enabled is False:
                return stats
            run = await repo.create_run(self.provider, source, mode, search_scope)

        try:
            async with self._client_context() as client:
                candidates = await self._discover(client, stats, search_scope, limit, max_pages)
                unique_candidates = self._dedupe(candidates)
                stats.listings_seen = len(unique_candidates)

                if dry_run:
                    stats.samples = [self._sample(candidate) for candidate in unique_candidates[:5]]
                    return stats

                assert repo is not None
                assert source is not None
                seen_external_ids = set()
                for candidate in unique_candidates:
                    seen_external_ids.add(candidate.external_id)
                    content_hash = stable_content_hash(candidate_hash_payload(candidate))
                    existing = await repo.get_existing(source.id, candidate.external_id)
                    detail = await self._maybe_fetch_detail(client, candidate, existing, content_hash, mode, stats)
                    result = await repo.upsert_property(
                        source,
                        candidate,
                        content_hash,
                        detail,
                        run_id=run.id if run else None,
                    )
                    if result.created:
                        stats.new_properties += 1
                    elif result.reactivated:
                        stats.reactivated_properties += 1
                    elif result.updated:
                        stats.updated_properties += 1
                    else:
                        stats.unchanged_properties += 1

                if mode == "full":
                    await repo.reconcile_missing(
                        source,
                        seen_external_ids,
                        run.id if run else None,
                        stats,
                        MissingPolicy(
                            missing_threshold=self.settings.missing_threshold,
                            removal_after_hours=self.settings.removal_after_hours,
                        ),
                    )

                if run:
                    await repo.finish_run(run, "success", stats)
                await self.session.commit()
                return stats
        except Exception as exc:
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
    ) -> list[PropertyCandidate]:
        candidates: list[PropertyCandidate] = []
        page = 1
        max_pages = self.settings.max_pages if max_pages is None else max_pages

        while page and (max_pages <= 0 or page <= max_pages):
            try:
                html = await self.provider.fetch_listing_page(client, page, search_scope)
                stats.pages_fetched += 1
                listing_page = self.provider.parse_listing_page(html, page, search_scope)
                for candidate in listing_page.candidates:
                    candidates.append(self.provider.normalize_listing(candidate))
                    if limit and len(candidates) >= limit:
                        return candidates
                page = listing_page.next_page
            except ScraperHTTPError as exc:
                stats.http_errors.append({"page": page, "status_code": exc.status_code, "url": exc.url})
                break
            except Exception as exc:
                stats.parse_errors.append({"page": page, "error": str(exc)[:500]})
                break

        return candidates

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
            detail = self.provider.parse_property_detail(html, candidate)
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

    def _sample(self, candidate: PropertyCandidate) -> dict[str, Any]:
        return {
            "external_id": candidate.external_id,
            "source_url": candidate.source_url,
            "title": candidate.title,
            "price": str(candidate.price) if candidate.price is not None else None,
        }

    def _client_context(self):
        if self.http_client is not None:
            return self.http_client
        return SharedScraperHTTPClient(self.settings, provider_headers=self.provider.headers)
