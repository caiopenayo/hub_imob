from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[3]
load_dotenv(ROOT_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL must be set")

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be set")


def _to_async_database_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


ASYNC_DATABASE_URL = _to_async_database_url(DATABASE_URL)

# Host onde o backend vai rodar
# 0.0.0.0 significa aceitar conexões vindas de qualquer interface de rede
BACKEND_HOST = os.getenv("BACKEND_HOST", "0.0.0.0")

# Porta onde o backend vai rodar
# os.getenv retorna string, por isso convertemos para int
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))

# URL do Redis, caso o projeto use Redis para filas, cache ou jobs em background
REDIS_URL = os.getenv("REDIS_URL")


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class SearchLLMSettings:
    enabled: bool = True
    provider: str = "local_huggingface"
    model_id: str = "Qwen/Qwen2.5-0.5B-Instruct"
    revision: str | None = None
    device: str = "auto"
    max_input_tokens: int = 1024
    max_new_tokens: int = 192
    timeout_seconds: float = 180
    max_concurrency: int = 1
    max_query_characters: int = 500
    load_failure_cooldown_seconds: int = 300
    price_target_tolerance: float = 0.10
    area_target_tolerance: float = 0.10
    max_per_page: int = 50
    log_raw_query: bool = False
    remote_url: str | None = None
    remote_api_key: str | None = None
    remote_generate_path: str = "/generate"
    remote_repair_path: str = "/repair"
    remote_repair_enabled: bool = True


def load_search_llm_settings() -> SearchLLMSettings:
    return SearchLLMSettings(
        enabled=_bool_env("SEARCH_LLM_ENABLED", True),
        provider=os.getenv("SEARCH_LLM_PROVIDER", "local_huggingface"),
        model_id=os.getenv("SEARCH_LLM_MODEL_ID", "Qwen/Qwen2.5-0.5B-Instruct"),
        revision=os.getenv("SEARCH_LLM_REVISION") or None,
        device=os.getenv("SEARCH_LLM_DEVICE", "auto"),
        max_input_tokens=_int_env("SEARCH_LLM_MAX_INPUT_TOKENS", 1024),
        max_new_tokens=_int_env("SEARCH_LLM_MAX_NEW_TOKENS", 192),
        timeout_seconds=_float_env("SEARCH_LLM_TIMEOUT_SECONDS", 180),
        max_concurrency=_int_env("SEARCH_LLM_MAX_CONCURRENCY", 1),
        max_query_characters=_int_env("SEARCH_LLM_MAX_QUERY_CHARACTERS", 500),
        load_failure_cooldown_seconds=_int_env("SEARCH_LLM_LOAD_FAILURE_COOLDOWN_SECONDS", 300),
        price_target_tolerance=_float_env("SEARCH_PRICE_TARGET_TOLERANCE", 0.10),
        area_target_tolerance=_float_env("SEARCH_AREA_TARGET_TOLERANCE", 0.10),
        max_per_page=_int_env("SEARCH_MAX_PER_PAGE", 50),
        log_raw_query=_bool_env("SEARCH_LOG_RAW_QUERY", False),
        remote_url=os.getenv("SEARCH_LLM_REMOTE_URL") or None,
        remote_api_key=os.getenv("SEARCH_LLM_REMOTE_API_KEY") or None,
        remote_generate_path=os.getenv("SEARCH_LLM_REMOTE_GENERATE_PATH", "/generate"),
        remote_repair_path=os.getenv("SEARCH_LLM_REMOTE_REPAIR_PATH", "/repair"),
        remote_repair_enabled=_bool_env("SEARCH_LLM_REMOTE_REPAIR_ENABLED", True),
    )
