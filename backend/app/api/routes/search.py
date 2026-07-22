from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException

from ...schemas.search import (
    NaturalSearchItem,
    NaturalSearchRequest,
    NaturalSearchResponse,
    SearchInterpretRequest,
    SearchInterpretResponse,
)
from ...search.exceptions import (
    SearchIntentGenerationError,
    SearchIntentParsingError,
    SearchIntentValidationError,
    SearchModelUnavailableError,
)
from ...search.interpreter import SearchIntentInterpreter
from ...search.schemas import SearchIntent
from ...search.service import NaturalLanguageSearchService
from .properties import serialize_property


router = APIRouter(prefix="/search", tags=["search"])


class SearchIntentRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)


def get_natural_search_service() -> NaturalLanguageSearchService:
    return NaturalLanguageSearchService()


@router.post("/intent", response_model=SearchIntent)
async def interpret_search_intent(payload: SearchIntentRequest):
    interpreter = SearchIntentInterpreter()
    try:
        return await interpreter.interpret(payload.query)
    except SearchModelUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Search model is unavailable") from exc
    except SearchIntentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (SearchIntentParsingError, SearchIntentGenerationError) as exc:
        raise HTTPException(status_code=422, detail="Could not interpret search query") from exc


@router.post("/interpret", response_model=SearchInterpretResponse)
async def interpret_natural_search(
    payload: SearchInterpretRequest,
    service: NaturalLanguageSearchService = Depends(get_natural_search_service),
):
    try:
        result = await service.interpret(payload.query)
        return SearchInterpretResponse(
            query=result.query,
            intent=result.intent,
            normalized_intent=result.normalized_intent,
            normalization_issues=result.normalization_issues,
            model=result.model,
        )
    except SearchModelUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Search model is unavailable") from exc
    except SearchIntentValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (SearchIntentParsingError, SearchIntentGenerationError) as exc:
        raise HTTPException(status_code=422, detail="Could not interpret search query") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unexpected search error") from exc


@router.post("", response_model=NaturalSearchResponse)
@router.post("/", response_model=NaturalSearchResponse)
async def natural_search(
    payload: NaturalSearchRequest,
    service: NaturalLanguageSearchService = Depends(get_natural_search_service),
):
    try:
        result = await service.search(payload.query, page=payload.page, per_page=payload.per_page)
        items = []
        for ranked in result.items:
            serialized = serialize_property(ranked.property)
            item_data = serialized.model_dump()
            item_data.update(ranked.match.model_dump())
            items.append(NaturalSearchItem.model_validate(item_data))
        return NaturalSearchResponse(
            query=result.query,
            intent=result.intent,
            normalized_intent=result.normalized_intent,
            normalization_issues=result.normalization_issues,
            items=items,
            meta={"page": result.page, "per_page": result.per_page, "total": result.total},
            model=result.model,
        )
    except SearchModelUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Search model is unavailable") from exc
    except SearchIntentValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (SearchIntentParsingError, SearchIntentGenerationError) as exc:
        raise HTTPException(status_code=422, detail="Could not interpret search query") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unexpected search error") from exc
