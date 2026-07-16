# Imob Site Monorepo

Monorepo skeleton for Next.js frontend + FastAPI backend + Python scrapers.

Structure (initial):
- frontend/  — Next.js app
- backend/   — FastAPI app
- scrapers/  — scraper scripts

See `.env.example` for environment variables.

Backend dev server:

```bash
# From the repository root
uvicorn backend.app.main:app --reload

# Or from inside backend/
uvicorn app.main:app --reload
```
