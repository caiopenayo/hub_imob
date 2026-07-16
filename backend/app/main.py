# Importa a classe principal do FastAPI, usada para criar a aplicação/backend
from fastapi import FastAPI

# Importa o middleware de CORS, que controla quais frontends podem acessar a API
from fastapi.middleware.cors import CORSMiddleware

# Importa as rotas relacionadas aos imóveis
from .api.routes.properties import router as properties_router

# Importa as rotas relacionadas ao processo de scraping
from .api.routes.scrape import router as scrape_router

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

# Registra na aplicação as rotas de imóveis, como listar ou buscar propriedades
app.include_router(properties_router)

# Registra na aplicação as rotas de scraping, como iniciar coleta de anúncios
app.include_router(scrape_router)

# Cria uma rota GET em /health para verificar se o backend está funcionando
@app.get("/health")
async def health():
    # Retorna uma resposta simples indicando que a API está online
    return {"status": "ok"}
