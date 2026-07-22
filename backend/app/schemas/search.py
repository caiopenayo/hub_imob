from __future__ import annotations

from pydantic import BaseModel, Field

from backend.app.schemas.property import PropertyRead
from backend.app.search.schemas import (
    NormalizationIssue,
    NormalizedSearchIntent,
    PropertyMatchInfo,
    SearchIntent,
    SearchModelInfo,
)


class SearchInterpretRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)


class SearchInterpretResponse(BaseModel):
    query: str
    intent: SearchIntent
    normalized_intent: NormalizedSearchIntent
    normalization_issues: list[NormalizationIssue] = Field(default_factory=list)
    model: SearchModelInfo


class NaturalSearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=50)


class NaturalSearchItem(PropertyRead):
    match_score: float = Field(ge=0, le=1)
    matched_preferences: list[str] = Field(default_factory=list)
    missing_preferences: list[str] = Field(default_factory=list)
    unknown_preferences: list[str] = Field(default_factory=list)


class NaturalSearchResponse(BaseModel):
    query: str
    intent: SearchIntent
    normalized_intent: NormalizedSearchIntent
    normalization_issues: list[NormalizationIssue] = Field(default_factory=list)
    items: list[NaturalSearchItem]
    meta: dict
    model: SearchModelInfo
