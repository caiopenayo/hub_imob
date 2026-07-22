from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Property
from backend.app.db.property_filters import visible_property_filters

from .schemas import NormalizationIssue, NormalizedSearchIntent, SearchIntent


CITY_ALIASES = {
    "sp": "São Paulo",
    "sampa": "São Paulo",
    "sao paulo": "São Paulo",
}

NEIGHBORHOOD_ALIASES = {
    "vl madalena": "Vila Madalena",
    "vila mada": "Vila Madalena",
    "jardins": "Jardim Paulista",
    "jd paulista": "Jardim Paulista",
    "itaim": "Itaim Bibi",
}

FUZZY_THRESHOLD = 0.95


@dataclass
class LocationIndex:
    cities_by_key: dict[str, str] = field(default_factory=dict)
    neighborhoods_by_key: dict[str, str] = field(default_factory=dict)
    neighborhood_cities: dict[str, set[str]] = field(default_factory=dict)


class LocationRepository:
    async def load_index(self, session: AsyncSession) -> LocationIndex:
        stmt = (
            select(Property.city, Property.neighborhood)
            .where(*visible_property_filters())
            .where(Property.city.is_not(None))
        )
        result = await session.execute(stmt)
        index = LocationIndex()
        for city, neighborhood in result.all():
            city = _clean_text(city)
            neighborhood = _clean_text(neighborhood)
            if city:
                index.cities_by_key.setdefault(text_key(city), city)
            if city and neighborhood:
                neighborhood_key = text_key(neighborhood)
                index.neighborhoods_by_key.setdefault(neighborhood_key, neighborhood)
                index.neighborhood_cities.setdefault(neighborhood_key, set()).add(city)
        return index


class SearchIntentNormalizer:
    def __init__(self, location_repository: LocationRepository | None = None):
        self.location_repository = location_repository or LocationRepository()

    async def normalize(self, session: AsyncSession, intent: SearchIntent) -> tuple[NormalizedSearchIntent, list[NormalizationIssue]]:
        index = await self.location_repository.load_index(session)
        issues: list[NormalizationIssue] = []
        city = self._resolve_city(intent.city, index, issues)
        neighborhoods = self._resolve_neighborhoods(intent.neighborhoods, city, index, issues)

        for unresolved in intent.unresolved_terms:
            issues.append(
                NormalizationIssue(
                    field="unresolved_terms",
                    original_value=unresolved,
                    reason="term was not mapped to a supported search field",
                )
            )

        normalized = NormalizedSearchIntent(
            transaction_type=intent.transaction_type,
            property_type=intent.property_type,
            city=city,
            neighborhoods=neighborhoods,
            price=intent.price,
            area_m2=intent.area_m2,
            bedrooms=intent.bedrooms,
            bathrooms=intent.bathrooms,
            parking_spaces=intent.parking_spaces,
            balcony=intent.balcony,
            unresolved_terms=list(intent.unresolved_terms),
            clarification_needed=intent.clarification_needed,
            clarification_question=intent.clarification_question,
        )
        return normalized, issues

    def _resolve_city(
        self,
        city: str | None,
        index: LocationIndex,
        issues: list[NormalizationIssue],
    ) -> str | None:
        if not city:
            return None
        resolved = resolve_canonical(city, index.cities_by_key, CITY_ALIASES)
        if resolved:
            return resolved
        issues.append(
            NormalizationIssue(
                field="city",
                original_value=city,
                reason="city was not found in current property inventory",
            )
        )
        return None

    def _resolve_neighborhoods(
        self,
        neighborhoods: list[str],
        city: str | None,
        index: LocationIndex,
        issues: list[NormalizationIssue],
    ) -> list[str]:
        resolved: list[str] = []
        seen: set[str] = set()
        for neighborhood in neighborhoods:
            canonical = resolve_canonical(neighborhood, index.neighborhoods_by_key, NEIGHBORHOOD_ALIASES)
            if not canonical:
                issues.append(
                    NormalizationIssue(
                        field="neighborhoods",
                        original_value=neighborhood,
                        reason="neighborhood was not found in current property inventory",
                    )
                )
                continue

            key = text_key(canonical)
            cities = index.neighborhood_cities.get(key, set())
            if city and cities and city not in cities:
                issues.append(
                    NormalizationIssue(
                        field="neighborhoods",
                        original_value=neighborhood,
                        reason=f"neighborhood is not associated with city {city}",
                    )
                )
                continue

            if key not in seen:
                seen.add(key)
                resolved.append(canonical)
        return resolved


def resolve_canonical(value: str, canonical_by_key: dict[str, str], aliases: dict[str, str] | None = None) -> str | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    key = text_key(cleaned)
    if key in canonical_by_key:
        return canonical_by_key[key]

    aliases = aliases or {}
    alias_target = aliases.get(key)
    if alias_target:
        target_key = text_key(alias_target)
        return canonical_by_key.get(target_key)

    return _safe_fuzzy_match(key, canonical_by_key)


def _safe_fuzzy_match(value_key: str, canonical_by_key: dict[str, str]) -> str | None:
    matches = sorted(
        (
            (SequenceMatcher(None, value_key, candidate_key).ratio(), candidate_key)
            for candidate_key in canonical_by_key
        ),
        reverse=True,
    )
    if not matches or matches[0][0] < FUZZY_THRESHOLD:
        return None
    if len(matches) > 1 and matches[0][0] - matches[1][0] < 0.03:
        return None
    return canonical_by_key[matches[0][1]]


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    return cleaned or None


def text_key(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value)
    without_accents = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", without_accents).strip().casefold()
