# Permite usar tipos opcionais, ou seja, valores que podem ser str/int/float ou None
from typing import Optional
from urllib.parse import urlsplit

# APIRouter cria um grupo de rotas
# Depends injeta dependências, como a sessão do banco
# HTTPException permite retornar erros HTTP
# Query permite validar parâmetros da URL
from fastapi import APIRouter, Depends, HTTPException, Query

# Tipo da sessão assíncrona do banco de dados
from sqlalchemy.ext.asyncio import AsyncSession

# Função que cria/fornece uma sessão com o banco
from ...db.session import get_session

# Schemas Pydantic usados para validar entrada e formatar saída
from ...schemas.property import PriceHistoryItem, PropertyCreate, PropertyRead, PropertyList

# Funções CRUD que acessam o banco
from ...db.crud import (
    create_or_update_property,
    get_property_by_id,
    get_property_price_history,
    list_properties as list_properties_crud,
)

from ...core.security import require_api_key


# Cria um grupo de rotas com prefixo /properties
# Todas as rotas deste arquivo começam com /properties
router = APIRouter(prefix="/properties", tags=["properties"])


def is_generated_zimoveis_thumbnail(url: str | None) -> bool:
    if not url:
        return False
    parts = urlsplit(url)
    return parts.netloc.endswith("zimoveis.com.br") and parts.path.startswith("/thumb/")


def display_image_urls(urls: list[str | None]) -> list[str]:
    seen = set()
    normalized = []
    for url in urls:
        if not url:
            continue
        key = url.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(url)

    preferred = [url for url in normalized if not is_generated_zimoveis_thumbnail(url)]
    return preferred or normalized


def serialize_property(property_obj) -> PropertyRead:
    property_read = PropertyRead.model_validate(property_obj)
    metadata = dict(property_read.metadata or {})
    photos = [
        photo.source_url
        for photo in getattr(property_obj, "photos", []) or []
        if getattr(photo, "is_active", True) is not False and getattr(photo, "source_url", None)
    ]
    metadata_images = metadata.get("images") if isinstance(metadata.get("images"), list) else []
    image_urls = display_image_urls(
        photos
        or [
            property_read.main_image_url,
            metadata.get("main_image") if isinstance(metadata.get("main_image"), str) else None,
            *[url for url in metadata_images if isinstance(url, str)],
        ]
    )
    if image_urls:
        property_read.main_image_url = image_urls[0]
        metadata["images"] = image_urls
        metadata["main_image"] = image_urls[0]
        property_read.metadata = metadata
    return property_read

# Rota GET /properties/
# Lista imóveis com paginação e filtros opcionais
@router.get("/", response_model=PropertyList)
async def list_properties(
    # Página atual; mínimo 1
    page: int = Query(1, ge=1),

    # Quantidade de itens por página; mínimo 1 e máximo 100
    per_page: int = Query(20, ge=1, le=100),

    # Filtro opcional por cidade
    city: Optional[str] = None,

    # Filtro opcional por preço mínimo
    min_price: Optional[float] = None,

    # Filtro opcional por preço máximo
    max_price: Optional[float] = None,

    # Filtro opcional por número de quartos
    bedrooms: Optional[int] = None,

    # Ordenação opcional da listagem
    sort: Optional[str] = None,

    # Recebe uma sessão do banco automaticamente via Depends
    session: AsyncSession = Depends(get_session),
):
    # Busca imóveis no banco usando os filtros e a paginação
    items, total = await list_properties_crud(
        session=session,
        city=city,
        min_price=min_price,
        max_price=max_price,
        bedrooms=bedrooms,
        sort=sort,

         # Número máximo de imóveis retornados
        limit=per_page,

        # Quantidade de imóveis que devem ser pulados
        # Exemplo: página 2 com 20 por página pula os primeiros 20
        offset=(page - 1) * per_page,
    )
    # Retorna os imóveis e metadados da paginação
    return {"items": [serialize_property(i) for i in items], "meta": {"page": page, "per_page": per_page, "total": total}}


@router.get("/{property_id}/price-history", response_model=list[PriceHistoryItem])
async def get_property_price_history_endpoint(property_id: str, session: AsyncSession = Depends(get_session)):
    property_obj = await get_property_by_id(session, property_id)
    if not property_obj:
        raise HTTPException(status_code=404, detail="Property not found")
    history = await get_property_price_history(session, property_obj.id)
    return [
        {"price": float(item["price"]), "detected_at": item["detected_at"]}
        for item in history
    ]


# Rota GET /properties/{property_id}
# Busca um imóvel específico pelo ID
@router.get("/{property_id}", response_model=PropertyRead)
async def get_property(property_id: str, session: AsyncSession = Depends(get_session)):
    # Busca o imóvel no banco pelo ID
    property_obj = await get_property_by_id(session, property_id)

    # Se não encontrar, retorna erro 404
    if not property_obj:
        raise HTTPException(status_code=404, detail="Property not found")
    # Retorna o imóvel encontrado
    return serialize_property(property_obj)


# Rota POST /properties/
# Cria ou atualiza um imóvel no banco
@router.post("/", response_model=PropertyRead)
async def ingest_property(
    payload: PropertyCreate,
    _: None = Depends(require_api_key),
    session: AsyncSession = Depends(get_session),
):
    try:
        # Cria um novo imóvel ou atualiza um existente
        created = await create_or_update_property(session, payload)
        # Retorna o imóvel criado/atualizado
        return created
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
