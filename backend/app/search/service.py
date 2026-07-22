from __future__ import annotations

from dataclasses import dataclass
import logging
from time import perf_counter
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import SearchLLMSettings, load_search_llm_settings
from backend.app.db.session import AsyncSessionLocal
from backend.app.llm.prompts import SEARCH_INTENT_PROMPT_VERSION

from .interpreter import SearchIntentInterpreter
from .normalizer import SearchIntentNormalizer
from .query import PropertyQueryBuilder, PropertyRanker, RankedProperty
from .schemas import NormalizationIssue, NormalizedSearchIntent, SearchIntent, SearchModelInfo


logger = logging.getLogger(__name__)


class AsyncSessionContextFactory(Protocol):
    def __call__(self) -> Any:
        ...


@dataclass
class SearchInterpretationResult:
    query: str
    intent: SearchIntent
    normalized_intent: NormalizedSearchIntent
    normalization_issues: list[NormalizationIssue]
    model: SearchModelInfo


@dataclass
class PropertySearchResult:
    query: str
    intent: SearchIntent
    normalized_intent: NormalizedSearchIntent
    normalization_issues: list[NormalizationIssue]
    items: list[RankedProperty]
    total: int
    page: int
    per_page: int
    model: SearchModelInfo


class PropertySearchService:
    def __init__(
        self,
        query_builder: PropertyQueryBuilder | None = None,
        ranker: PropertyRanker | None = None,
    ):
        self.query_builder = query_builder or PropertyQueryBuilder()
        self.ranker = ranker or PropertyRanker()

    async def search(
        self,
        session: AsyncSession,
        intent: NormalizedSearchIntent,
        page: int,
        per_page: int,
    ) -> tuple[list[RankedProperty], int]:
        stmt = self.query_builder.build(intent)
        result = await session.execute(stmt)
        properties = result.scalars().unique().all()
        ranked = [RankedProperty(property=prop, match=self.ranker.rank(prop, intent)) for prop in properties]
        ranked.sort(
            key=lambda item: (
                item.match.match_score,
                item.property.updated_at or item.property.last_seen_at or item.property.created_at,
            ),
            reverse=True,
        )
        start = (page - 1) * per_page
        return ranked[start : start + per_page], len(ranked)


class NaturalLanguageSearchService:
    def __init__(
        self,
        interpreter: SearchIntentInterpreter | None = None,
        normalizer: SearchIntentNormalizer | None = None,
        property_search_service: PropertySearchService | None = None,
        session_factory: AsyncSessionContextFactory = AsyncSessionLocal,
        settings: SearchLLMSettings | None = None,
    ):
        self.settings = settings or load_search_llm_settings()
        self.interpreter = interpreter or SearchIntentInterpreter(settings=self.settings)
        self.normalizer = normalizer or SearchIntentNormalizer()
        self.property_search_service = property_search_service or PropertySearchService()
        self.session_factory = session_factory

    async def interpret(self, query: str) -> SearchInterpretationResult:
        request_id = str(uuid4())
        start = perf_counter()
        try:
            intent = await self.interpreter.interpret(query)
        except Exception:
            self._log(
                "natural_search_interpret",
                request_id=request_id,
                query=query,
                interpretation_duration_ms=_elapsed_ms(start),
                status="failed",
            )
            raise
        interpretation_duration_ms = _elapsed_ms(start)

        normalize_start = perf_counter()
        async with self.session_factory() as session:
            normalized_intent, issues = await self.normalizer.normalize(session, intent)
        normalization_duration_ms = _elapsed_ms(normalize_start)

        self._log(
            "natural_search_interpret",
            request_id=request_id,
            query=query,
            interpretation_duration_ms=interpretation_duration_ms,
            normalization_duration_ms=normalization_duration_ms,
            result_count=None,
            status="success",
        )
        return SearchInterpretationResult(
            query=query,
            intent=intent,
            normalized_intent=normalized_intent,
            normalization_issues=issues,
            model=self.model_info(),
        )

    async def search(self, query: str, page: int, per_page: int) -> PropertySearchResult:
        request_id = str(uuid4())
        page = max(1, page)
        per_page = min(max(1, per_page), max(1, self.settings.max_per_page))

        start = perf_counter()
        try:
            intent = await self.interpreter.interpret(query)
        except Exception:
            self._log(
                "natural_search",
                request_id=request_id,
                query=query,
                interpretation_duration_ms=_elapsed_ms(start),
                status="failed",
            )
            raise
        interpretation_duration_ms = _elapsed_ms(start)

        normalize_start = perf_counter()
        async with self.session_factory() as session:
            normalized_intent, issues = await self.normalizer.normalize(session, intent)
            normalization_duration_ms = _elapsed_ms(normalize_start)

            query_start = perf_counter()
            items, total = await self.property_search_service.search(session, normalized_intent, page, per_page)
            database_query_duration_ms = _elapsed_ms(query_start)

        self._log(
            "natural_search",
            request_id=request_id,
            query=query,
            interpretation_duration_ms=interpretation_duration_ms,
            normalization_duration_ms=normalization_duration_ms,
            database_query_duration_ms=database_query_duration_ms,
            result_count=total,
            status="success",
        )
        return PropertySearchResult(
            query=query,
            intent=intent,
            normalized_intent=normalized_intent,
            normalization_issues=issues,
            items=items,
            total=total,
            page=page,
            per_page=per_page,
            model=self.model_info(),
        )

    def model_info(self) -> SearchModelInfo:
        return SearchModelInfo(provider=self.settings.provider, model_id=self.settings.model_id)

    def _log(self, event: str, **payload: Any) -> None:
        safe_payload = {
            "event": event,
            "model_provider": self.settings.provider,
            "model_id": self.settings.model_id,
            "prompt_version": SEARCH_INTENT_PROMPT_VERSION,
            **payload,
        }
        if not self.settings.log_raw_query:
            safe_payload.pop("query", None)
        logger.info(event, extra=safe_payload)


def _elapsed_ms(start: float) -> int:
    return int((perf_counter() - start) * 1000)
