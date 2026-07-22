from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TransactionType(str, Enum):
    sale = "sale"
    rent = "rent"


class PropertyType(str, Enum):
    apartment = "apartment"
    house = "house"
    studio = "studio"
    commercial = "commercial"
    land = "land"


class RequirementLevel(str, Enum):
    required = "required"
    preferred = "preferred"


class NumericCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_value: float | None = None
    max_value: float | None = None
    target_value: float | None = None
    importance: RequirementLevel = RequirementLevel.required

    @field_validator("min_value", "max_value", "target_value")
    @classmethod
    def numbers_must_be_non_negative(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("numeric criteria must be non-negative")
        return value

    @model_validator(mode="after")
    def validate_range(self) -> NumericCriterion:
        if self.min_value is None and self.max_value is None and self.target_value is None:
            raise ValueError("numeric criterion must include min_value, max_value or target_value")
        if self.min_value is not None and self.max_value is not None and self.min_value > self.max_value:
            raise ValueError("min_value must be less than or equal to max_value")
        return self


class BooleanCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: bool
    importance: RequirementLevel = RequirementLevel.required


class SearchIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_type: TransactionType | None = None
    property_type: PropertyType | None = None

    city: str | None = None
    neighborhoods: list[str] = Field(default_factory=list)

    price: NumericCriterion | None = None
    area_m2: NumericCriterion | None = None
    bedrooms: NumericCriterion | None = None
    bathrooms: NumericCriterion | None = None
    parking_spaces: NumericCriterion | None = None

    balcony: BooleanCriterion | None = None

    unresolved_terms: list[str] = Field(default_factory=list)
    clarification_needed: bool = False
    clarification_question: str | None = None

    @field_validator("city")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("neighborhoods", "unresolved_terms")
    @classmethod
    def normalize_non_empty_text_list(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            if not isinstance(value, str):
                raise ValueError("list values must be strings")
            value = value.strip()
            if not value:
                raise ValueError("list values must not be empty")
            normalized.append(value)
        return normalized

    @field_validator("clarification_question")
    @classmethod
    def normalize_clarification_question(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def validate_semantics(self) -> SearchIntent:
        if self.clarification_question and not self.clarification_needed:
            raise ValueError("clarification_question should only be populated when clarification is needed")

        self._validate_upper_bound("price", self.price, 1_000_000_000)
        self._validate_upper_bound("area_m2", self.area_m2, 100_000)
        self._validate_upper_bound("bedrooms", self.bedrooms, 100)
        self._validate_upper_bound("bathrooms", self.bathrooms, 100)
        self._validate_upper_bound("parking_spaces", self.parking_spaces, 100)
        return self

    @staticmethod
    def _validate_upper_bound(name: str, criterion: NumericCriterion | None, upper_bound: float) -> None:
        if criterion is None:
            return
        for field_name in ("min_value", "max_value", "target_value"):
            value = getattr(criterion, field_name)
            if value is not None and value > upper_bound:
                raise ValueError(f"{name}.{field_name} exceeds a reasonable upper bound")


class NormalizationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    original_value: str
    reason: str


class NormalizedSearchIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_type: TransactionType | None = None
    property_type: PropertyType | None = None

    city: str | None = None
    neighborhoods: list[str] = Field(default_factory=list)

    price: NumericCriterion | None = None
    area_m2: NumericCriterion | None = None
    bedrooms: NumericCriterion | None = None
    bathrooms: NumericCriterion | None = None
    parking_spaces: NumericCriterion | None = None

    balcony: BooleanCriterion | None = None

    unresolved_terms: list[str] = Field(default_factory=list)
    clarification_needed: bool = False
    clarification_question: str | None = None


class SearchModelInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model_id: str


class PropertyMatchInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_score: float = Field(ge=0, le=1)
    matched_preferences: list[str] = Field(default_factory=list)
    missing_preferences: list[str] = Field(default_factory=list)
    unknown_preferences: list[str] = Field(default_factory=list)
