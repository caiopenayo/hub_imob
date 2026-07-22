from __future__ import annotations

from backend.app.core.config import SearchLLMSettings, load_search_llm_settings
from backend.app.llm.base import SearchIntentModelClient
from backend.app.llm.factory import get_default_search_intent_client

from .exceptions import (
    SearchIntentGenerationError,
    SearchIntentParsingError,
    SearchIntentValidationError,
    SearchModelUnavailableError,
)
from .parser import parse_search_intent_output
from .schemas import SearchIntent


class SearchIntentInterpreter:
    def __init__(
        self,
        model_client: SearchIntentModelClient | None = None,
        settings: SearchLLMSettings | None = None,
    ):
        self.settings = settings or load_search_llm_settings()
        self.model_client = model_client

    async def interpret(self, query: str) -> SearchIntent:
        normalized_query = self._validate_query(query)
        client = self._model_client()
        raw_output = await client.generate_search_intent(normalized_query)
        try:
            return parse_search_intent_output(raw_output)
        except (SearchIntentParsingError, SearchIntentValidationError) as first_error:
            repair_output = await client.repair_search_intent(raw_output, str(first_error))
            try:
                return parse_search_intent_output(repair_output)
            except (SearchIntentParsingError, SearchIntentValidationError) as second_error:
                raise SearchIntentGenerationError(
                    "model did not produce a valid SearchIntent after one repair attempt"
                ) from second_error

    def _validate_query(self, query: str) -> str:
        if not isinstance(query, str):
            raise SearchIntentValidationError("query must be a string")
        query = query.strip()
        if not query:
            raise SearchIntentValidationError("query must not be empty")
        max_characters = max(1, self.settings.max_query_characters)
        if len(query) > max_characters:
            raise SearchIntentValidationError(f"query exceeds {max_characters} characters")
        return query

    def _model_client(self) -> SearchIntentModelClient:
        if not self.settings.enabled and self.model_client is None:
            raise SearchModelUnavailableError("search LLM is disabled")
        return self.model_client or get_default_search_intent_client(self.settings)
