from __future__ import annotations

from backend.app.core.config import SearchLLMSettings, load_search_llm_settings
from backend.app.search.exceptions import SearchModelUnavailableError

from .base import SearchIntentModelClient
from .local_huggingface import LocalHuggingFaceSearchIntentClient, get_search_model_status as get_local_search_model_status
from .remote_http import RemoteHTTPSearchIntentClient, get_remote_search_model_status


_default_clients: dict[tuple[object, ...], SearchIntentModelClient] = {}


def get_default_search_intent_client(settings: SearchLLMSettings | None = None) -> SearchIntentModelClient:
    settings = settings or load_search_llm_settings()
    provider = _provider(settings)
    key = _client_key(settings, provider)
    if key not in _default_clients:
        if provider == "local_huggingface":
            _default_clients[key] = LocalHuggingFaceSearchIntentClient(settings)
        elif provider == "remote_http":
            _default_clients[key] = RemoteHTTPSearchIntentClient(settings)
        else:
            raise SearchModelUnavailableError("unsupported search LLM provider")
    return _default_clients[key]


def get_search_model_status(settings: SearchLLMSettings | None = None) -> dict:
    settings = settings or load_search_llm_settings()
    provider = _provider(settings)
    if provider == "local_huggingface":
        return get_local_search_model_status(settings)
    if provider == "remote_http":
        return get_remote_search_model_status(settings)
    return {"status": "unconfigured", "provider": provider, "model_id": settings.model_id}


def _provider(settings: SearchLLMSettings) -> str:
    return settings.provider.strip().casefold()


def _client_key(settings: SearchLLMSettings, provider: str) -> tuple[object, ...]:
    if provider == "local_huggingface":
        return (provider, settings.model_id, settings.revision, settings.device)
    if provider == "remote_http":
        return (
            provider,
            settings.remote_url,
            bool(settings.remote_api_key),
            settings.remote_generate_path,
            settings.remote_repair_path,
            settings.remote_repair_enabled,
        )
    return (provider,)


def clear_default_search_intent_clients_for_tests() -> None:
    _default_clients.clear()
