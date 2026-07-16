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
