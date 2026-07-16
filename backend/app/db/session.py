''' Configuração do banco de dados e sessão assíncrona usando SQLAlchemy. '''

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)

# Importa a URL assíncrona do banco definida nas configurações do projeto
from ..core.config import ASYNC_DATABASE_URL

if ASYNC_DATABASE_URL is None:
    raise RuntimeError("DATABASE_URL must be set")

# Cria o engine assíncrono do SQLAlchemy
# echo=False evita mostrar todas as queries SQL no terminal
engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=False,
    connect_args={"statement_cache_size": 0},
)

# Cria uma fábrica de sessões assíncronas
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Dependência usada pelo FastAPI para fornecer uma sessão do banco por requisição
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
