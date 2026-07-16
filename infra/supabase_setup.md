# Supabase Setup Guide

1. Create a Supabase project at https://app.supabase.com.
2. In the project settings -> Database, copy the Postgres connection string and set it as `DATABASE_URL` in your deployment environment (and local `.env`).
3. In the project settings -> API, copy the `SERVICE_ROLE` key and set it as `SUPABASE_SERVICE_ROLE_KEY` in backend/scraper envs. Keep this secret server-side only.
4. Optional: enable connection pooling (pgbouncer) if available to avoid connection exhaustion from serverless hosts.
5. Run DB migrations from backend (locally or CI):

```bash
cd backend
# create a venv, install requirements
pip install -r requirements.txt
alembic upgrade head
```

6. Configure Row-Level Security policies if you expose user-specific data and want fine-grained access control.
7. (Optional) Use Supabase Storage for images; store image URLs in the `properties.metadata` or a dedicated table.
8. For scrapers: use `SUPABASE_SERVICE_ROLE_KEY` only if writing directly to the DB; otherwise POST normalized data to your FastAPI ingest endpoint.

Security notes:
- Never expose `SUPABASE_SERVICE_ROLE_KEY` to the browser.
- Restrict network access to your DB if possible and use least-privilege service accounts.
