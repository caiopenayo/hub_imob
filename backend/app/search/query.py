from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import Select

from backend.app.core.config import SearchLLMSettings, load_search_llm_settings
from backend.app.db.models import Property, PropertyOffer
from backend.app.db.property_filters import visible_property_filters

from .schemas import (
    BooleanCriterion,
    NormalizedSearchIntent,
    NumericCriterion,
    PropertyMatchInfo,
    PropertyType,
    RequirementLevel,
    TransactionType,
)


PROPERTY_TYPE_TERMS = {
    PropertyType.apartment: ["apart", "cobertura", "flat"],
    PropertyType.house: ["casa", "sobrado"],
    PropertyType.studio: ["studio", "kitnet", "loft"],
    PropertyType.commercial: ["comercial", "loja", "sala", "prédio", "predio"],
    PropertyType.land: ["terreno", "lote"],
}


@dataclass(frozen=True)
class RankedProperty:
    property: Property
    match: PropertyMatchInfo


class PropertyQueryBuilder:
    def __init__(self, settings: SearchLLMSettings | None = None):
        self.settings = settings or load_search_llm_settings()

    def build(self, intent: NormalizedSearchIntent) -> Select[tuple[Property]]:
        if not isinstance(intent, NormalizedSearchIntent):
            raise TypeError("PropertyQueryBuilder accepts only NormalizedSearchIntent")

        stmt = select(Property).options(selectinload(Property.offers), selectinload(Property.photos)).where(
            *visible_property_filters()
        )

        if intent.transaction_type:
            stmt = stmt.where(self._transaction_type_filter(intent.transaction_type))
        if intent.property_type:
            stmt = stmt.where(self._property_type_filter(intent.property_type))
        if intent.city:
            stmt = stmt.where(Property.city == intent.city)
        if intent.neighborhoods:
            stmt = stmt.where(Property.neighborhood.in_(intent.neighborhoods))

        stmt = self._apply_required_numeric(stmt, Property.price, intent.price, self.settings.price_target_tolerance)
        stmt = self._apply_required_numeric(stmt, Property.area_m2, intent.area_m2, self.settings.area_target_tolerance)
        stmt = self._apply_required_numeric(stmt, Property.bedrooms, intent.bedrooms)
        stmt = self._apply_required_numeric(stmt, Property.bathrooms, intent.bathrooms)
        stmt = self._apply_required_numeric(stmt, Property.parking_spaces, intent.parking_spaces)

        if intent.balcony and intent.balcony.importance == RequirementLevel.required:
            stmt = stmt.where(Property.balcony.is_(intent.balcony.value))

        return stmt.order_by(Property.updated_at.desc().nullslast(), Property.last_seen_at.desc().nullslast())

    def _apply_required_numeric(
        self,
        stmt: Select[tuple[Property]],
        column: Any,
        criterion: NumericCriterion | None,
        target_tolerance: float | None = None,
    ) -> Select[tuple[Property]]:
        if criterion is None or criterion.importance != RequirementLevel.required:
            return stmt
        if criterion.min_value is not None:
            stmt = stmt.where(column >= criterion.min_value)
        if criterion.max_value is not None:
            stmt = stmt.where(column <= criterion.max_value)
        if criterion.target_value is not None:
            tolerance = max(0, target_tolerance if target_tolerance is not None else 0)
            lower = criterion.target_value * (1 - tolerance)
            upper = criterion.target_value * (1 + tolerance)
            stmt = stmt.where(column >= lower, column <= upper)
        return stmt

    def _transaction_type_filter(self, transaction_type: TransactionType):
        value = transaction_type.value
        return or_(
            func.lower(Property.transaction_type) == value,
            Property.offers.any(and_(func.lower(PropertyOffer.purpose) == value, PropertyOffer.status == "ACTIVE")),
        )

    def _property_type_filter(self, property_type: PropertyType):
        terms = PROPERTY_TYPE_TERMS[property_type]
        searchable = func.lower(func.coalesce(Property.property_type, "") + " " + func.coalesce(Property.property_subtype, ""))
        return or_(*[searchable.like(f"%{term}%") for term in terms])


class PropertyRanker:
    WEIGHTS = {
        "price": 0.25,
        "area_m2": 0.20,
        "neighborhood": 0.15,
        "bedrooms": 0.10,
        "bathrooms": 0.10,
        "parking_spaces": 0.10,
        "balcony": 0.10,
    }

    def __init__(self, settings: SearchLLMSettings | None = None):
        self.settings = settings or load_search_llm_settings()

    def rank(self, prop: Property, intent: NormalizedSearchIntent) -> PropertyMatchInfo:
        score_parts: list[tuple[float, float]] = []
        matched_preferences: list[str] = []
        missing_preferences: list[str] = []
        unknown_preferences: list[str] = []

        if intent.price:
            self._add_numeric_score(score_parts, "price", prop.price, intent.price, self.settings.price_target_tolerance)
            self._collect_preference(
                "price",
                prop.price,
                intent.price,
                matched_preferences,
                missing_preferences,
                unknown_preferences,
                self.settings.price_target_tolerance,
            )
        if intent.area_m2:
            self._add_numeric_score(score_parts, "area_m2", prop.area_m2, intent.area_m2, self.settings.area_target_tolerance)
            self._collect_preference(
                "area_m2",
                prop.area_m2,
                intent.area_m2,
                matched_preferences,
                missing_preferences,
                unknown_preferences,
                self.settings.area_target_tolerance,
            )
        if intent.neighborhoods:
            score_parts.append((self.WEIGHTS["neighborhood"], 1.0 if prop.neighborhood in intent.neighborhoods else 0.0))

        self._add_numeric_score(score_parts, "bedrooms", prop.bedrooms, intent.bedrooms)
        self._collect_preference("bedrooms", prop.bedrooms, intent.bedrooms, matched_preferences, missing_preferences, unknown_preferences)
        self._add_numeric_score(score_parts, "bathrooms", prop.bathrooms, intent.bathrooms)
        self._collect_preference("bathrooms", prop.bathrooms, intent.bathrooms, matched_preferences, missing_preferences, unknown_preferences)
        self._add_numeric_score(score_parts, "parking_spaces", prop.parking_spaces, intent.parking_spaces)
        self._collect_preference(
            "parking_spaces",
            prop.parking_spaces,
            intent.parking_spaces,
            matched_preferences,
            missing_preferences,
            unknown_preferences,
        )

        if intent.balcony:
            balcony_score = self._boolean_score(prop.balcony, intent.balcony)
            score_parts.append((self.WEIGHTS["balcony"], balcony_score))
            if intent.balcony.importance == RequirementLevel.preferred:
                if prop.balcony is None:
                    unknown_preferences.append("balcony")
                elif prop.balcony is intent.balcony.value:
                    matched_preferences.append("balcony")
                else:
                    missing_preferences.append("balcony")

        match_score = self._weighted_average(score_parts)
        return PropertyMatchInfo(
            match_score=round(match_score, 4),
            matched_preferences=matched_preferences,
            missing_preferences=missing_preferences,
            unknown_preferences=unknown_preferences,
        )

    def _add_numeric_score(
        self,
        score_parts: list[tuple[float, float]],
        field: str,
        value: Any,
        criterion: NumericCriterion | None,
        target_tolerance: float | None = None,
    ) -> None:
        if criterion is None:
            return
        score_parts.append((self.WEIGHTS[field], self._numeric_score(value, criterion, target_tolerance)))

    def _collect_preference(
        self,
        field: str,
        value: Any,
        criterion: NumericCriterion | None,
        matched: list[str],
        missing: list[str],
        unknown: list[str],
        target_tolerance: float | None = None,
    ) -> None:
        if criterion is None or criterion.importance != RequirementLevel.preferred:
            return
        if value is None:
            unknown.append(field)
        elif self._numeric_matches(value, criterion, target_tolerance):
            matched.append(field)
        else:
            missing.append(field)

    def _numeric_score(self, value: Any, criterion: NumericCriterion, target_tolerance: float | None = None) -> float:
        if value is None:
            return 0.0
        numeric_value = float(value)
        if criterion.target_value is not None:
            tolerance = target_tolerance if target_tolerance is not None else 0.10
            distance = abs(numeric_value - criterion.target_value)
            divisor = max(criterion.target_value * tolerance * 2, 1)
            return max(0.0, min(1.0, 1 - distance / divisor))
        return 1.0 if self._numeric_matches(value, criterion, target_tolerance) else 0.0

    def _numeric_matches(self, value: Any, criterion: NumericCriterion, target_tolerance: float | None = None) -> bool:
        if value is None:
            return False
        numeric_value = Decimal(str(value))
        if criterion.min_value is not None and numeric_value < Decimal(str(criterion.min_value)):
            return False
        if criterion.max_value is not None and numeric_value > Decimal(str(criterion.max_value)):
            return False
        if criterion.target_value is not None:
            tolerance = Decimal(str(target_tolerance if target_tolerance is not None else 0.10))
            target = Decimal(str(criterion.target_value))
            return target * (Decimal("1") - tolerance) <= numeric_value <= target * (Decimal("1") + tolerance)
        return True

    def _boolean_score(self, value: bool | None, criterion: BooleanCriterion) -> float:
        if value is None:
            return 0.0
        return 1.0 if value is criterion.value else 0.0

    def _weighted_average(self, score_parts: list[tuple[float, float]]) -> float:
        total_weight = sum(weight for weight, _score in score_parts)
        if not total_weight:
            return 1.0
        return max(0.0, min(1.0, sum(weight * score for weight, score in score_parts) / total_weight))
