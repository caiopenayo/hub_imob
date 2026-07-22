import logging
from time import perf_counter
from uuid import uuid4

# Importa a classe principal do FastAPI, usada para criar a aplicação/backend
from fastapi import FastAPI, Request

# Importa o middleware de CORS, que controla quais frontends podem acessar a API
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

# Importa as rotas relacionadas aos imóveis
from .api.routes.properties import router as properties_router

# Importa as rotas relacionadas ao processo de scraping
from .api.routes.scrape import router as scrape_router

# Importa as rotas relacionadas à busca em linguagem natural
from .api.routes.search import router as search_router
from .db.session import AsyncSessionLocal
from .llm.factory import get_search_model_status


logger = logging.getLogger(__name__)

# Cria a aplicação FastAPI e define o título que aparece na documentação automática
app = FastAPI(title="Imob Backend")

# Adiciona configuração de CORS para permitir que o frontend acesse o backend
app.add_middleware(
    CORSMiddleware,
    # Permite requisições vindas do frontend local rodando na porta 3000
    allow_origins=["http://localhost:3000"],

    # Permite envio de cookies, headers de autenticação ou credenciais
    allow_credentials=True,

    # Permite todos os métodos HTTP: GET, POST, PUT, DELETE etc.
    allow_methods=["*"],

    # Permite todos os headers nas requisições
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_metadata(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    start = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request_failed",
            extra={
                "event": "request_failed",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "duration_ms": int((perf_counter() - start) * 1000),
            },
        )
        raise

    duration_ms = int((perf_counter() - start) * 1000)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = str(duration_ms)
    logger.info(
        "request_completed",
        extra={
            "event": "request_completed",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response

# Registra na aplicação as rotas de imóveis, como listar ou buscar propriedades
app.include_router(properties_router)

# Registra na aplicação as rotas de scraping, como iniciar coleta de anúncios
app.include_router(scrape_router)

# Registra as rotas de interpretação de busca em linguagem natural
app.include_router(search_router)

# Cria uma rota GET em /health para verificar se o backend está funcionando
@app.get("/health")
async def health():
    # Retorna uma resposta simples indicando que a API está online
    return {"status": "ok"}


@app.get("/ready")
async def readiness():
    dependencies = {"database": "unknown"}
    status = "ready"
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        dependencies["database"] = "ok"
    except Exception:
        dependencies["database"] = "failed"
        status = "not_ready"

    return {"status": status, "dependencies": dependencies}


@app.get("/health/search-model")
async def search_model_health():
    return get_search_model_status()
