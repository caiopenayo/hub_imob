from __future__ import annotations

from typing import Protocol


class SearchIntentModelClient(Protocol):
    async def generate_search_intent(self, query: str) -> str:
        ...

    async def repair_search_intent(self, malformed_output: str, validation_error: str) -> str:
        ...
