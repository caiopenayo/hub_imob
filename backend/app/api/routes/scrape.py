from datetime import datetime
import re
from typing import Any, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.security import require_api_key
from ...db.session import get_session
from ...db.crud import (
    create_job_log,
    get_job_log_by_id,
    get_source_by_id_or_key,
    has_running_full_job,
    list_enabled_sources,
    list_job_logs,
    update_job_log,
)
from ...schemas.job import JobLogRead

router = APIRouter(prefix="/scrape", tags=["scrape"])

# Schema do corpo da requisição para disparar scraping
class ScrapeTrigger(BaseModel):
    # Lista opcional de fontes específicas que devem ser raspadas    
    source_ids: Optional[List[str]] = None
    source_keys: Optional[List[str]] = None
    provider: Optional[str] = None

    # Modo de scraping: "delta" para buscar mudanças ou "full" para buscar tudo
    mode: str = "delta"
    scope: Optional[dict[str, Any]] = None
    max_pages: Optional[int] = Field(default=None, ge=1)
    max_details: Optional[int] = Field(default=None, ge=0)
    dry_run: bool = False


class ScheduleTrigger(BaseModel):
    provider: str
    job_type: str
    dry_run: bool = False
    max_pages: Optional[int] = Field(default=None, ge=1)
    max_details: Optional[int] = Field(default=None, ge=0)


def _normalize_scope(scope: dict[str, Any] | None) -> dict[str, Any] | None:
    if not scope:
        return None
    normalized = {key: value for key, value in scope.items() if value not in (None, "")}
    query = normalized.pop("query", None)
    if query and "q" not in normalized:
        normalized["q"] = query
    return normalized or None


def _validate_scope(scope: dict[str, Any] | None) -> dict[str, Any] | None:
    if not scope:
        return scope
    purpose = scope.get("purpose")
    if purpose and purpose not in {"sale", "rent", "venda", "locacao", "locação"}:
        raise HTTPException(status_code=400, detail="scope.purpose must be sale or rent")
    slug_re = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    for key in ("state_slug", "city_slug"):
        value = scope.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not slug_re.match(value):
            raise HTTPException(status_code=400, detail=f"scope.{key} must be a valid slug")
    return scope


def _expanded_scopes(scope: dict[str, Any] | None) -> list[dict[str, Any] | None]:
    if not scope or "purposes" not in scope:
        return [_validate_scope(scope)]
    purposes = scope.get("purposes")
    if isinstance(purposes, str):
        purposes = [purposes]
    if not isinstance(purposes, list) or not purposes:
        raise HTTPException(status_code=400, detail="scope.purposes must be a non-empty list")
    scopes = []
    for purpose in purposes:
        next_scope = {key: value for key, value in scope.items() if key != "purposes"}
        next_scope["purpose"] = purpose
        scopes.append(_validate_scope(next_scope))
    return scopes


async def _resolve_provider_sources(session: AsyncSession, source_ids: Optional[List[str]]):
    from scrapers.core.registry import load_provider, registered_provider_keys

    sources = []
    if source_ids:
        for source_id in source_ids:
            source = await get_source_by_id_or_key(session, source_id)
            if not source:
                raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")
            sources.append(source)
    else:
        enabled_sources = await list_enabled_sources(session)
        sources = [source for source in enabled_sources if source.key in registered_provider_keys()]

    resolved = []
    for source in sources:
        if source.enabled is False:
            raise HTTPException(status_code=400, detail=f"Source disabled: {source.key or source.id}")
        if not source.key:
            raise HTTPException(status_code=400, detail=f"Source has no provider key: {source.id}")
        provider = load_provider(source.key)
        if provider is None:
            raise HTTPException(status_code=400, detail=f"No provider registered for source: {source.key}")
        resolved.append((source, provider))

    if not resolved:
        raise HTTPException(status_code=400, detail="No enabled provider sources found")
    return resolved

# Função executada em background para rodar os scrapers
async def _background_scrape_job(job_id: str, source_ids: Optional[List[str]], mode: str):
    """Run scrapers and ingest results directly into DB using internal CRUD helpers.

    This avoids making HTTP requests to the same process and keeps the job efficient.
    """
    print(f"[scrape job {job_id}] starting mode={mode} sources={source_ids}")
    from scrapers.run_scraper import run_scrapers
    from ...schemas.property import PropertyCreate
    from ...db.crud import create_or_update_property, update_job_log
    from ...db.session import AsyncSessionLocal

    try:
        results = []
        # Se fontes específicas foram informadas, roda scraper para cada fonte
        if source_ids:
            for s in source_ids:
                res = await run_scrapers(source=s, mode=mode)
                # Se a fonte retornou resultados, adiciona na lista final
                if res:
                    results.extend(res)
        # Se nenhuma fonte foi informada, roda todos os scrapers disponíveis
        else:
            results = await run_scrapers(mode=mode)

        ingested = 0
        # Abre uma nova sessão para salvar os imóveis encontrados
        async with AsyncSessionLocal() as session:
            # Percorre cada imóvel retornado pelos scrapers
            for item in results:
                try:
                    # Valida e transforma o dicionário em um schema PropertyCreate
                    payload = PropertyCreate(**item)
                    await create_or_update_property(session, payload)
                    ingested += 1
                except Exception as exc:
                    print(f"[scrape job {job_id}] failed ingest for item {item.get('external_id')}: {exc}")

        summary = {"ingested": ingested, "total": len(results)}
        async with AsyncSessionLocal() as session:
            await update_job_log(session, job_id, status='success', summary=summary)

        print(f"[scrape job {job_id}] completed: ingested={ingested} items")
    except Exception as exc:
        error_text = str(exc)
        async with AsyncSessionLocal() as session:
            await update_job_log(session, job_id, status='failed', error=error_text)
        print(f"[scrape job {job_id}] failed: {error_text}")


async def _background_provider_scrape_job(
    job_id: str,
    source_key: str,
    mode: str,
    scope: dict[str, Any] | None,
    max_pages: int | None,
    max_details: int | None,
    dry_run: bool,
):
    """Run a provider-backed scrape job.

    FastAPI BackgroundTasks is enough for this MVP. For production workloads with
    retries, concurrency control across processes, or long-running jobs, move this
    worker to a queue such as Celery, Dramatiq, RQ, or Arq.
    """
    from scrapers.core.engine import SyncEngine
    from scrapers.core.persistence import PropertyRepository
    from scrapers.core.registry import load_provider
    from scrapers.core.settings import load_scraper_settings
    from scrapers.core.types import SyncStats
    from ...db.session import AsyncSessionLocal

    provider = load_provider(source_key)
    async with AsyncSessionLocal() as session:
        repo = PropertyRepository(session)
        run = await repo.get_run(job_id)
        if not run:
            return
        try:
            if provider is None:
                raise RuntimeError(f"No provider registered for source: {source_key}")
            run.status = "running"
            run.started_at = run.started_at or datetime.utcnow()
            session.add(run)
            await session.commit()

            settings = load_scraper_settings()
            if dry_run:
                stats = await SyncEngine(provider=provider, settings=settings).run(
                    mode=mode,
                    search_scope=scope,
                    dry_run=True,
                    max_pages=max_pages,
                    max_details=max_details,
                )
                status = "success" if stats.completed and not stats.http_errors and not stats.parse_errors else "partial"
                run = await repo.get_run(job_id)
                await repo.finish_run(run, status, stats)
                await session.commit()
                return

            await SyncEngine(provider=provider, settings=settings, session=session).run(
                mode=mode,
                search_scope=scope,
                dry_run=False,
                max_pages=max_pages,
                max_details=max_details,
                run_id=job_id,
            )
        except Exception as exc:
            run = await repo.get_run(job_id)
            if run:
                await repo.finish_run(
                    run,
                    "failed",
                    stats=getattr(exc, "stats", None) or SyncStats(
                        provider_key=source_key,
                        mode=mode,
                        dry_run=dry_run,
                    ),
                    error=str(exc)[:1000],
                )
                await session.commit()

# Rota GET /scrape/jobs
# Lista os jobs de scraping já executados ou em execução
@router.get("/jobs", response_model=dict)
async def list_jobs(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    offset = (page - 1) * per_page
    items, total = await list_job_logs(session, status=status, limit=per_page, offset=offset)
    return {"items": [JobLogRead.model_validate(item) for item in items], "meta": {"page": page, "per_page": per_page, "total": total}}

# Rota GET /scrape/jobs/{job_id}
# Busca um job específico pelo ID
@router.get("/jobs/{job_id}", response_model=JobLogRead)
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)):
    job = await get_job_log_by_id(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/schedules", response_model=dict)
async def list_sale_schedules(_: None = Depends(require_api_key)):
    from scrapers.core.scheduler import list_schedules

    return {"items": await list_schedules()}


@router.post("/schedules/run", response_model=dict)
async def run_sale_schedule_job(payload: ScheduleTrigger, _: None = Depends(require_api_key)):
    from scrapers.core.scheduler import run_manual_job

    allowed = {"sale_health_check", "sale_priority_crawl", "sale_full_crawl"}
    aliases = {
        "health-check": "sale_health_check",
        "priority-crawl": "sale_priority_crawl",
        "full-crawl": "sale_full_crawl",
    }
    job_type = aliases.get(payload.job_type, payload.job_type)
    if job_type not in allowed:
        raise HTTPException(status_code=400, detail="unsupported scheduler job_type")
    return await run_manual_job(
        provider_key=payload.provider,
        job_type=job_type,
        dry_run=payload.dry_run,
        max_pages=payload.max_pages,
        max_details=payload.max_details,
    )


# Rota POST /scrape/trigger
# Dispara um job de scraping
@router.post("/trigger")
async def trigger_scrape(
    payload: ScrapeTrigger,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_api_key),
    session: AsyncSession = Depends(get_session),
):
    """Legacy trigger. Requires `X-API-KEY` header equal to `SECRET_KEY` in env."""
    mode = payload.mode or "delta"
    job = await create_job_log(session, job_name='scraper', source_ids=payload.source_ids, mode=mode)
    job_id = str(job.id)
    background_tasks.add_task(_background_scrape_job, job_id, payload.source_ids, mode)

    return {"job_id": job_id}


@router.post("")
@router.post("/", include_in_schema=False)
async def trigger_provider_scrape(
    payload: ScrapeTrigger,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_api_key),
    session: AsyncSession = Depends(get_session),
):
    mode = payload.mode or "delta"
    if mode not in {"delta", "full"}:
        raise HTTPException(status_code=400, detail="mode must be 'delta' or 'full'")

    source_ids = payload.source_keys or payload.source_ids or ([payload.provider] if payload.provider else None)
    resolved_sources = await _resolve_provider_sources(session, source_ids)
    jobs = []
    for source, provider in resolved_sources:
        base_scope = _normalize_scope(payload.scope) or provider.default_search_scope
        for scope in _expanded_scopes(base_scope):
            scope = scope or provider.default_search_scope
            if mode == "full" and not payload.dry_run:
                running = await has_running_full_job(session, source.id, provider.source_key, scope)
                if running:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Full scrape already running for {provider.source_key} and this scope",
                    )
            job = await create_job_log(
                session,
                job_name="scraper",
                source_ids=[str(source.id)],
                source_id=source.id,
                provider_key=provider.source_key,
                search_scope=scope,
                mode=mode,
                status="pending",
            )
            jobs.append(job)
            background_tasks.add_task(
                _background_provider_scrape_job,
                str(job.id),
                provider.source_key,
                mode,
                scope,
                payload.max_pages,
                payload.max_details,
                payload.dry_run,
            )

    return {"job_id": str(jobs[0].id), "job_ids": [str(job.id) for job in jobs]}
