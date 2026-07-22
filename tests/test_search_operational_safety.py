import asyncio
import json

from fastapi import HTTPException
import pytest

from backend.app.api.routes.search import SearchIntentRequest, interpret_search_intent
import backend.app.main as main_module
from backend.app.core.config import SearchLLMSettings
from backend.app.llm.factory import (
    clear_default_search_intent_clients_for_tests,
    get_default_search_intent_client,
    get_search_model_status as get_configured_search_model_status,
)
from backend.app.llm.local_huggingface import LocalHuggingFaceSearchIntentClient, get_search_model_status as get_local_search_model_status
from backend.app.llm.remote_http import RemoteHTTPSearchIntentClient
import backend.app.search.interpreter as interpreter_module
from backend.app.search.exceptions import SearchModelUnavailableError
from backend.app.search.query import PropertyQueryBuilder
from backend.app.search.schemas import NormalizedSearchIntent


def reset_model_state():
    cls = LocalHuggingFaceSearchIntentClient
    cls._tokenizer = None
    cls._model = None
    cls._device = None
    cls._model_key = None
    cls._loading = False
    cls._load_error = None
    cls._load_failed_at = None


def test_search_intent_endpoint_sanitizes_model_error(monkeypatch):
    class BrokenClient:
        async def generate_search_intent(self, query: str) -> str:
            raise SearchModelUnavailableError("/home/user/.cache/huggingface/private/path")

        async def repair_search_intent(self, malformed_output: str, validation_error: str) -> str:
            raise AssertionError("repair should not run")

    monkeypatch.setattr(interpreter_module, "load_search_llm_settings", lambda: SearchLLMSettings())
    monkeypatch.setattr(interpreter_module, "get_default_search_intent_client", lambda _settings=None: BrokenClient())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(interpret_search_intent(SearchIntentRequest(query="apartamento em Pinheiros")))

    assert getattr(exc_info.value, "status_code") == 503
    assert getattr(exc_info.value, "detail") == "Search model is unavailable"


def test_search_query_builder_parameterizes_untrusted_location_values():
    malicious_city = "São Paulo'; DROP TABLE properties; --"
    malicious_neighborhood = "Pinheiros'); DELETE FROM sources; --"
    intent = NormalizedSearchIntent(city=malicious_city, neighborhoods=[malicious_neighborhood])

    stmt = PropertyQueryBuilder().build(intent)
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    sql = str(compiled)

    assert "DROP TABLE" not in sql
    assert "DELETE FROM" not in sql
    assert "DROP TABLE" in repr(compiled.params)
    assert "DELETE FROM" in repr(compiled.params)


def test_search_model_status_does_not_load_model():
    reset_model_state()

    status = get_local_search_model_status(SearchLLMSettings(enabled=True, model_id="test/model", device="cpu"))

    assert status["status"] == "unloaded"
    assert status["model_id"] == "test/model"
    assert LocalHuggingFaceSearchIntentClient._model is None
    assert LocalHuggingFaceSearchIntentClient._tokenizer is None


def test_search_model_status_reports_disabled_loading_and_failed_without_internal_details():
    reset_model_state()
    disabled = get_local_search_model_status(SearchLLMSettings(enabled=False, model_id="test/model", device="cpu"))
    assert disabled["status"] == "disabled"

    LocalHuggingFaceSearchIntentClient._loading = True
    loading = get_local_search_model_status(SearchLLMSettings(enabled=True, model_id="test/model", device="cpu"))
    assert loading["status"] == "loading"

    LocalHuggingFaceSearchIntentClient._loading = False
    LocalHuggingFaceSearchIntentClient._model_key = ("test/model", None, "cpu")
    LocalHuggingFaceSearchIntentClient._load_error = "/tmp/private/model/path"
    failed = get_local_search_model_status(SearchLLMSettings(enabled=True, model_id="test/model", device="cpu"))
    assert failed == {
        "status": "failed",
        "provider": "local_huggingface",
        "model_id": "test/model",
        "revision_pinned": False,
        "device": "cpu",
        "error": "model failed to load",
    }
    reset_model_state()


def test_model_load_failure_is_cached(monkeypatch):
    reset_model_state()
    client = LocalHuggingFaceSearchIntentClient(
        SearchLLMSettings(model_id="broken/model", device="cpu", load_failure_cooldown_seconds=300)
    )
    calls = 0

    def broken_torch():
        nonlocal calls
        calls += 1
        raise SearchModelUnavailableError("torch is not installed")

    monkeypatch.setattr(client, "_torch", broken_torch)

    with pytest.raises(SearchModelUnavailableError):
        client._ensure_model_sync()
    with pytest.raises(SearchModelUnavailableError):
        client._ensure_model_sync()

    assert calls == 1
    reset_model_state()


def test_generation_oom_returns_sanitized_unavailable_error(monkeypatch):
    client = LocalHuggingFaceSearchIntentClient(SearchLLMSettings(timeout_seconds=5))
    cleared = False

    def clear_cache():
        nonlocal cleared
        cleared = True

    monkeypatch.setattr(client, "_clear_cuda_cache", clear_cache)

    with pytest.raises(SearchModelUnavailableError) as exc_info:
        client._raise_generation_runtime_error(RuntimeError("CUDA error: out of memory while allocating tensor"))

    assert str(exc_info.value) == "local search LLM ran out of memory"
    assert cleared is True


def test_liveness_health_is_lightweight():
    response = asyncio.run(main_module.health())

    assert response == {"status": "ok"}


def test_readiness_checks_database_without_model_load(monkeypatch):
    reset_model_state()
    executed = False

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def execute(self, statement):
            nonlocal executed
            executed = True
            return None

    monkeypatch.setattr(main_module, "AsyncSessionLocal", lambda: FakeSession())

    response = asyncio.run(main_module.readiness())

    assert response == {"status": "ready", "dependencies": {"database": "ok"}}
    assert executed is True
    assert LocalHuggingFaceSearchIntentClient._model is None


def test_search_model_health_endpoint_does_not_load_model():
    reset_model_state()

    response = asyncio.run(main_module.search_model_health())

    assert response["status"] in {"disabled", "unloaded", "failed"}
    assert LocalHuggingFaceSearchIntentClient._model is None


class StubResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.payload = payload or {}

    def json(self):
        return self.payload


class StubHTTPClient:
    def __init__(self, response):
        self.response = response
        self.requests = []

    async def post(self, url, json, headers, timeout):
        self.requests.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return self.response


def test_remote_http_client_sends_only_minimal_generate_payload():
    http_client = StubHTTPClient(
        StubResponse(
            payload={
                "intent": {
                    "property_type": "apartment",
                    "neighborhoods": ["Pinheiros"],
                    "price": {"max_value": 1000000, "importance": "required"},
                }
            }
        )
    )
    settings = SearchLLMSettings(
        provider="remote_http",
        remote_url="https://colab-example.trycloudflare.com",
        remote_api_key="secret-token",
        max_new_tokens=192,
        timeout_seconds=30,
    )
    client = RemoteHTTPSearchIntentClient(settings, http_client=http_client)

    output = asyncio.run(client.generate_search_intent("apartamento em Pinheiros até 1 milhão"))

    assert json.loads(output)["neighborhoods"] == ["Pinheiros"]
    request = http_client.requests[0]
    assert request["url"] == "https://colab-example.trycloudflare.com/generate"
    assert request["json"] == {
        "query": "apartamento em Pinheiros até 1 milhão",
        "max_new_tokens": 192,
    }
    assert request["headers"]["Authorization"] == "Bearer secret-token"
    assert "DATABASE_URL" not in repr(request["json"])
    assert "SUPABASE" not in repr(request["json"])


def test_remote_http_client_sends_minimal_repair_payload():
    http_client = StubHTTPClient(StubResponse(payload={"output": '{"property_type":"apartment"}'}))
    settings = SearchLLMSettings(
        provider="remote_http",
        remote_url="https://colab-example.trycloudflare.com/",
        remote_api_key="secret-token",
        remote_repair_path="/repair",
    )
    client = RemoteHTTPSearchIntentClient(settings, http_client=http_client)

    output = asyncio.run(client.repair_search_intent('{"price":{}}', "price is invalid"))

    assert output == '{"property_type":"apartment"}'
    request = http_client.requests[0]
    assert request["url"] == "https://colab-example.trycloudflare.com/repair"
    assert set(request["json"]) == {"malformed_output", "validation_error", "max_new_tokens"}


def test_remote_http_client_sanitizes_server_errors():
    http_client = StubHTTPClient(StubResponse(status_code=500, payload={"detail": "/tmp/private/path"}))
    settings = SearchLLMSettings(provider="remote_http", remote_url="https://colab-example.trycloudflare.com")
    client = RemoteHTTPSearchIntentClient(settings, http_client=http_client)

    with pytest.raises(SearchModelUnavailableError) as exc_info:
        asyncio.run(client.generate_search_intent("apartamento em Pinheiros"))

    assert str(exc_info.value) == "remote search LLM returned a server error"
    assert "/tmp/private/path" not in str(exc_info.value)


def test_factory_selects_remote_provider_and_status_hides_secret():
    clear_default_search_intent_clients_for_tests()
    settings = SearchLLMSettings(
        provider="remote_http",
        remote_url="https://colab-example.trycloudflare.com",
        remote_api_key="secret-token",
    )

    client = get_default_search_intent_client(settings)
    status = get_configured_search_model_status(settings)

    assert isinstance(client, RemoteHTTPSearchIntentClient)
    assert status == {
        "status": "configured",
        "provider": "remote_http",
        "model_id": "Qwen/Qwen2.5-0.5B-Instruct",
        "remote_url_configured": True,
        "remote_auth_configured": True,
    }
    assert "secret-token" not in repr(status)
    clear_default_search_intent_clients_for_tests()
