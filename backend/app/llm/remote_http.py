from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urljoin

import httpx

from backend.app.core.config import SearchLLMSettings, load_search_llm_settings
from backend.app.search.exceptions import SearchModelUnavailableError


logger = logging.getLogger(__name__)


class RemoteHTTPSearchIntentClient:
    def __init__(
        self,
        settings: SearchLLMSettings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.settings = settings or load_search_llm_settings()
        self._http_client = http_client

    async def generate_search_intent(self, query: str) -> str:
        payload = {
            "query": query,
            "max_new_tokens": max(1, self.settings.max_new_tokens),
        }
        return await self._post(self.settings.remote_generate_path, payload)

    async def repair_search_intent(self, malformed_output: str, validation_error: str) -> str:
        if not self.settings.remote_repair_enabled:
            raise SearchModelUnavailableError("remote search LLM repair is disabled")
        payload = {
            "malformed_output": malformed_output[:4000],
            "validation_error": validation_error[:2000],
            "max_new_tokens": max(1, self.settings.max_new_tokens),
        }
        return await self._post(self.settings.remote_repair_path, payload)

    async def _post(self, path: str, payload: dict[str, Any]) -> str:
        if not self.settings.enabled:
            raise SearchModelUnavailableError("remote search LLM is disabled")
        if not self.settings.remote_url:
            raise SearchModelUnavailableError("remote search LLM URL is not configured")

        url = _join_url(self.settings.remote_url, path)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.settings.remote_api_key:
            headers["Authorization"] = f"Bearer {self.settings.remote_api_key}"

        try:
            if self._http_client is not None:
                response = await self._http_client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=max(1, self.settings.timeout_seconds),
                )
            else:
                async with httpx.AsyncClient(timeout=max(1, self.settings.timeout_seconds)) as client:
                    response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise SearchModelUnavailableError("remote search LLM timed out") from exc
        except httpx.RequestError as exc:
            logger.info(
                "remote_search_llm_request_failed",
                extra={
                    "event": "remote_search_llm_request_failed",
                    "provider": "remote_http",
                    "path": path,
                    "error_type": type(exc).__name__,
                },
            )
            raise SearchModelUnavailableError("remote search LLM request failed") from exc

        if response.status_code == 401 or response.status_code == 403:
            raise SearchModelUnavailableError("remote search LLM authentication failed")
        if response.status_code == 404:
            raise SearchModelUnavailableError("remote search LLM endpoint was not found")
        if response.status_code == 429:
            raise SearchModelUnavailableError("remote search LLM is rate limited")
        if response.status_code >= 500:
            raise SearchModelUnavailableError("remote search LLM returned a server error")
        if response.status_code >= 400:
            raise SearchModelUnavailableError("remote search LLM returned an invalid response")

        try:
            data = response.json()
        except ValueError as exc:
            raise SearchModelUnavailableError("remote search LLM response was not JSON") from exc

        return _extract_model_output(data)


def _join_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/") + "/"
    return urljoin(base, path.lstrip("/"))


def _extract_model_output(data: Any) -> str:
    if not isinstance(data, dict):
        raise SearchModelUnavailableError("remote search LLM response must be an object")
    for key in ("output", "text", "generated_text"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    intent = data.get("intent")
    if isinstance(intent, dict):
        return json.dumps(intent, ensure_ascii=False)
    raise SearchModelUnavailableError("remote search LLM response did not include output")


def get_remote_search_model_status(settings: SearchLLMSettings | None = None) -> dict[str, Any]:
    settings = settings or load_search_llm_settings()
    if not settings.enabled:
        status = "disabled"
    elif settings.remote_url:
        status = "configured"
    else:
        status = "unconfigured"
    return {
        "status": status,
        "provider": "remote_http",
        "model_id": settings.model_id,
        "remote_url_configured": bool(settings.remote_url),
        "remote_auth_configured": bool(settings.remote_api_key),
    }
