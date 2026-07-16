import asyncio
from importlib import import_module
from typing import List, Dict, Any, Optional
import os
from pathlib import Path
import time
import json

import httpx
from dotenv import load_dotenv

from scrapers.core.engine import SyncEngine
from scrapers.core.settings import load_scraper_settings

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")


def load_source_module(source: str):
    return import_module(f"scrapers.sources.{source}")


def load_provider(source: str):
    mod = load_source_module(source)
    return getattr(mod, "provider", None)


async def run_scrapers(source: Optional[str] = None, mode: str = "delta") -> List[Dict[str, Any]]:
    """Run configured scrapers and return a list of normalized property dicts.

    Defaults to `scrapers.sources.idealista` when no source is provided.
    """
    results: List[Dict[str, Any]] = []
    target_source = source or "idealista"

    try:
        mod = load_source_module(target_source)
    except Exception:
        return []

    if hasattr(mod, "scrape"):
        res = await mod.scrape(mode=mode)
    elif hasattr(mod, "scrape_example"):
        res = await mod.scrape_example()
    else:
        res = []

    if isinstance(res, list):
        results.extend(res)
    return results


async def run_provider_sync(
    source: str,
    mode: str = "delta",
    dry_run: bool | None = None,
    limit: int | None = None,
    max_pages: int | None = None,
    search_scope: dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Run a source that implements the shared provider interface."""
    provider = load_provider(source)
    if provider is None:
        raise RuntimeError(f"Source '{source}' does not expose a provider")

    settings = load_scraper_settings()
    effective_dry_run = settings.dry_run if dry_run is None else dry_run
    if effective_dry_run:
        stats = await SyncEngine(provider=provider, settings=settings).run(
            mode=mode,
            search_scope=search_scope,
            dry_run=True,
            limit=limit,
            max_pages=max_pages,
        )
        return stats.as_summary()

    from backend.app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        stats = await SyncEngine(provider=provider, settings=settings, session=session).run(
            mode=mode,
            search_scope=search_scope,
            dry_run=False,
            limit=limit,
            max_pages=max_pages,
        )
        return stats.as_summary()


async def ingest_to_backend(items: List[Dict[str, Any]]) -> Dict[str, int]:
    """POST normalized items to backend `POST /properties`.

    Reads `BACKEND_URL` and `BACKEND_API_KEY` from env.
    Returns a simple summary dict with counts.
    """
    backend = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
    api_key = os.getenv("BACKEND_API_KEY")
    if not api_key:
        raise RuntimeError("BACKEND_API_KEY must be set when ingesting to the backend")

    headers = {"Content-Type": "application/json", "X-API-KEY": api_key}

    ingested = 0
    failed = 0

    async with httpx.AsyncClient(timeout=30) as client:
        for item in items:
            try:
                resp = await client.post(f"{backend}/properties/", json=item, headers=headers)
                if resp.status_code in (200, 201):
                    ingested += 1
                else:
                    failed += 1
                    print(f"ingest failed status={resp.status_code} body={resp.text}")
            except Exception as exc:
                failed += 1
                print(f"ingest exception: {exc}")

    return {"ingested": ingested, "failed": failed, "total": len(items)}


async def _run_once(
    source: Optional[str],
    mode: str,
    ingest: bool,
    dry_run: bool,
    limit: int | None,
    max_pages: int | None,
    search_scope: dict[str, Any] | None,
) -> Dict[str, Any]:
    if source:
        try:
            if load_provider(source) is not None:
                return await run_provider_sync(
                    source=source,
                    mode=mode,
                    dry_run=dry_run,
                    limit=limit,
                    max_pages=max_pages,
                    search_scope=search_scope,
                )
        except ModuleNotFoundError:
            return {"found": 0, "error": f"source '{source}' not found"}

    items = await run_scrapers(source=source, mode=mode)
    summary = {"found": len(items)}
    if dry_run:
        summary["samples"] = items[:5]
        return summary
    if ingest and items:
        res = await ingest_to_backend(items)
        summary.update(res)
    return summary


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run scrapers")
    parser.add_argument("--source", help="Optional source module to run")
    parser.add_argument("--mode", choices=["full", "delta"], default="delta")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and parse without persisting changes")
    parser.add_argument("--limit", type=int, default=None, help="Optional cap on discovered properties")
    parser.add_argument("--max-pages", type=int, default=None, help="Optional cap on listing pages")
    parser.add_argument("--search-q", help="Optional search query for providers that support q")
    parser.add_argument("--ingest", action="store_true", help="POST results to backend /properties")
    parser.add_argument("--interval", type=int, default=0, help="If set, run in loop every N minutes")
    args = parser.parse_args()
    search_scope = {"q": args.search_q} if args.search_q else None

    async def _loop():
        if args.interval and args.interval > 0:
            print(f"Starting scheduler: every {args.interval} minutes (ingest={args.ingest})")
            while True:
                start = time.time()
                try:
                    summary = await _run_once(
                        args.source,
                        args.mode,
                        args.ingest,
                        args.dry_run,
                        args.limit,
                        args.max_pages,
                        search_scope,
                    )
                    print("run summary:", json.dumps(summary, ensure_ascii=False, default=str))
                except Exception as exc:
                    print("run exception:", exc)
                elapsed = time.time() - start
                wait = max(0, args.interval * 60 - elapsed)
                await asyncio.sleep(wait)
        else:
            summary = await _run_once(
                args.source,
                args.mode,
                args.ingest,
                args.dry_run,
                args.limit,
                args.max_pages,
                search_scope,
            )
            print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))

    asyncio.run(_loop())


if __name__ == "__main__":
    main()
