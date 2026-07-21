# Importa datetime para registrar horários de início/fim dos jobs
from datetime import datetime

# select monta consultas SQL
# func permite usar funções SQL, como count()
import uuid

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

# Tipo da sessão assíncrona com o banco
from sqlalchemy.ext.asyncio import AsyncSession

# Importa os modelos/tabelas do banco
from ..db.models import JobLog, Property, PropertyEvent, Source

# Schema usado para validar dados de criação de imóvel
from ..schemas.property import PropertyCreate


# Busca um imóvel usando a combinação source_id + external_id
async def get_property_by_source_external(session: AsyncSession, source_id, external_id):
    # Monta uma query SELECT na tabela Property com dois filtros    
    stmt = (
        select(Property)
        .options(selectinload(Property.offers), selectinload(Property.photos))
        .where(Property.source_id == source_id, Property.external_id == external_id)
    )
    # Executa a query no banco    
    result = await session.execute(stmt)

    # Retorna o primeiro resultado encontrado (ou None se não houver)
    return result.scalars().first()

# Busca um imóvel pelo ID interno do banco
async def get_property_by_id(session: AsyncSession, property_id):
    stmt = select(Property).options(selectinload(Property.offers), selectinload(Property.photos)).where(Property.id == property_id)
    result = await session.execute(stmt)
    return result.scalars().first()


async def get_source_by_id_or_key(session: AsyncSession, source_id_or_key: str):
    parsed_uuid = None
    try:
        parsed_uuid = uuid.UUID(str(source_id_or_key))
    except (TypeError, ValueError):
        parsed_uuid = None

    if parsed_uuid:
        stmt = select(Source).where(Source.id == parsed_uuid)
    else:
        stmt = select(Source).where(Source.key == source_id_or_key)
    result = await session.execute(stmt)
    return result.scalars().first()


async def list_enabled_sources(session: AsyncSession):
    stmt = select(Source).where(Source.enabled.is_(True))
    result = await session.execute(stmt)
    return result.scalars().all()

# Lista imóveis com filtros opcionais e paginação
async def list_properties(
    session: AsyncSession,
    city: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    bedrooms: int | None = None,
    sort: str | None = None,
    limit: int = 20,
    offset: int = 0,
):
    # Query principal para buscar os imóveis
    visible_filters = [
        Property.status == "ACTIVE",
        Property.property_subtype.is_distinct_from("Comercial"),
    ]
    stmt = select(Property).options(selectinload(Property.offers), selectinload(Property.photos)).where(*visible_filters)

    # Query separada para contar o total de imóveis com os mesmos filtros
    count_stmt = select(func.count()).select_from(Property).where(*visible_filters)

    # Se cidade foi informada, filtra por cidade ignorando maiúsculas/minúsculas
    if city:
        stmt = stmt.where(Property.city.ilike(f"%{city}%"))
        count_stmt = count_stmt.where(Property.city.ilike(f"%{city}%"))

    # Se preço mínimo foi informado, filtra imóveis com preço >= min_price        
    if min_price is not None:
        stmt = stmt.where(Property.price >= min_price)
        count_stmt = count_stmt.where(Property.price >= min_price)
    if max_price is not None:
        stmt = stmt.where(Property.price <= max_price)
        count_stmt = count_stmt.where(Property.price <= max_price)
    if bedrooms is not None:
        stmt = stmt.where(Property.bedrooms == bedrooms)
        count_stmt = count_stmt.where(Property.bedrooms == bedrooms)

    if sort == "price_asc":
        stmt = stmt.order_by(Property.price.asc().nullslast())
    elif sort == "price_desc":
        stmt = stmt.order_by(Property.price.desc().nullslast())
    elif sort == "area_desc":
        stmt = stmt.order_by(Property.area_m2.desc().nullslast())
    elif sort == "bedrooms_desc":
        stmt = stmt.order_by(Property.bedrooms.desc().nullslast())
    elif sort == "recent":
        stmt = stmt.order_by(Property.updated_at.desc().nullslast(), Property.last_seen_at.desc().nullslast())

    total_result = await session.execute(count_stmt)
    # Pega o total encontrado; se vier None, usa 0
    total = total_result.scalar() or 0
    # Aplica paginação na query principal
    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    items = result.scalars().all()
    # Retorna a lista de imóveis e o total
    return items, total

# Cria um registro de job, por exemplo para acompanhar uma execução de scraping
async def create_job_log(
    session: AsyncSession,
    job_name: str,
    source_ids: list[str] | None,
    mode: str,
    source_id=None,
    provider_key: str | None = None,
    search_scope: dict | None = None,
    status: str = "running",
):
    # Cria um objeto JobLog ainda não salvo no banco
    job = JobLog(
        job_name=job_name,
        source_id=source_id,
        provider_key=provider_key,
        source_ids=source_ids,
        search_scope=search_scope,
        mode=mode,
        status=status,
        started_at=datetime.utcnow() if status == "running" else None,
    )
    # Adiciona o objeto na sessão
    session.add(job)
    # Salva no banco
    await session.commit()

    #Atualiza o objeto Python com os dados gerados pelo banco, como ID
    await session.refresh(job)
    return job


async def has_running_full_job(
    session: AsyncSession,
    source_id,
    provider_key: str,
    search_scope: dict | None,
):
    stmt = select(JobLog).where(
        JobLog.source_id == source_id,
        JobLog.provider_key == provider_key,
        JobLog.mode == "full",
        JobLog.status.in_(["pending", "running"]),
    )
    result = await session.execute(stmt)
    for job in result.scalars().all():
        if (job.search_scope or {}) == (search_scope or {}):
            return job
    return None

# Atualiza o status de um job existente
async def update_job_log(
    session: AsyncSession,
    job_id,
    status: str,
    summary: dict | None = None,
    error: str | None = None,
):
    # Busca o job pelo ID
    stmt = select(JobLog).where(JobLog.id == job_id)
    result = await session.execute(stmt)
    job = result.scalars().first()
    if not job:
        return None

    #Atualiza os campos do job
    job.status = status
    job.finished_at = datetime.utcnow()
    job.summary = summary
    job.error = error
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


# Lista registros de jobs com filtro opcional por status
async def list_job_logs(
    session: AsyncSession,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
):
    stmt = select(JobLog)
    count_stmt = select(func.count()).select_from(JobLog)
    if status:
        stmt = stmt.where(JobLog.status == status)
        count_stmt = count_stmt.where(JobLog.status == status)

    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0
    stmt = stmt.order_by(JobLog.started_at.desc().nullslast()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    items = result.scalars().all()
    return items, total

# Busca um job específico pelo ID
async def get_job_log_by_id(session: AsyncSession, job_id):
    stmt = select(JobLog).where(JobLog.id == job_id)
    result = await session.execute(stmt)
    return result.scalars().first()


async def get_property_price_history(session: AsyncSession, property_id):
    stmt = (
        select(PropertyEvent)
        .where(
            PropertyEvent.property_id == property_id,
            PropertyEvent.event_type.in_(["CREATED", "PRICE_CHANGED"]),
        )
        .order_by(PropertyEvent.detected_at.asc())
    )
    result = await session.execute(stmt)
    history = []
    for event in result.scalars().all():
        payload = event.new_value or {}
        price = payload.get("price")
        if price is None:
            continue
        history.append({"price": price, "detected_at": event.detected_at})
    return history

# Cria um imóvel novo ou atualiza um imóvel existente
async def create_or_update_property(session: AsyncSession, payload: PropertyCreate):
    # Converte o schema Pydantic em dicionário, ignorando campos não enviados
    data = payload.model_dump(exclude_unset=True)
    if "metadata" in data:
        data["metadata_json"] = data.pop("metadata")
    if not data.get("source_url"):
        data["source_url"] = data.get("url")
    if data.get("metadata_json") and not data.get("main_image_url"):
        metadata = data["metadata_json"]
        images = metadata.get("images") if isinstance(metadata, dict) else None
        data["main_image_url"] = metadata.get("main_image") or (images[0] if images else None)
    data["last_seen_at"] = datetime.utcnow()
    data["status"] = "ACTIVE"
    data["missing_since"] = None
    data["removed_at"] = None
    # Procura se já existe um imóvel da mesma fonte com o mesmo ID externo
    existing = await get_property_by_source_external(session, payload.source_id, payload.external_id)
    if existing:
        if existing.first_seen_at is None:
            existing.first_seen_at = datetime.utcnow()
        for key, value in data.items():
            if hasattr(existing, key):
                # Só atualiza campos que existem no modelo Property
                setattr(existing, key, value)
        session.add(existing)
        await session.commit()
        await session.refresh(existing)
        return existing

    # filter keys that are valid model attributes
    valid_data = {k: v for k, v in data.items() if hasattr(Property, k)}
    new = Property(**valid_data)
    session.add(new)
    await session.commit()
    await session.refresh(new)
    return new
