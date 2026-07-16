import asyncio
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.security import require_api_key
from ...db.session import get_session
from ...db.crud import create_job_log, update_job_log, get_job_log_by_id, list_job_logs
from ...schemas.job import JobLogRead

router = APIRouter(prefix="/scrape", tags=["scrape"])

# Schema do corpo da requisição para disparar scraping
class ScrapeTrigger(BaseModel):
    # Lista opcional de fontes específicas que devem ser raspadas    
    source_ids: Optional[List[str]] = None

    # Modo de scraping: "delta" para buscar mudanças ou "full" para buscar tudo
    mode: Optional[str] = "delta"  

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


# Rota POST /scrape/trigger
# Dispara um job de scraping
@router.post("/trigger")
async def trigger_scrape(
    payload: ScrapeTrigger,
    _: None = Depends(require_api_key),
    session: AsyncSession = Depends(get_session),
):
    """Trigger a scrape job. Requires `X-API-KEY` header equal to `SECRET_KEY` in env."""
    mode = payload.mode or "delta"
    job = await create_job_log(session, job_name='scraper', source_ids=payload.source_ids, mode=mode)
    job_id = str(job.id)
    # schedule background task
    asyncio.create_task(_background_scrape_job(job_id, payload.source_ids, mode))

    return {"job_id": job_id}
