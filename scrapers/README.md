# Scrapers

This folder contains simple scrapers that normalize property listings and either return the results or ingest them into the FastAPI backend.

Quick run examples:

Run single source (default `idealista`) and print results:

```bash
python -m scrapers.run_scraper
```

Run Professionecasa and print results:

```bash
python -m scrapers.run_scraper --source professionecasa
```

Run a provider implemented with the shared sync framework in dry-run mode:

```bash
python -m scrapers.run_scraper --source zimmermann --dry-run --mode delta --max-pages 1
```

Run a provider and persist changes directly to the database:

```bash
python -m scrapers.run_scraper --source zimmermann --mode full --max-pages 10
```

Run and POST results to backend `POST /properties` (set `BACKEND_URL` if your backend isn't localhost, and set `BACKEND_API_KEY` to the backend `SECRET_KEY`):

```bash
BACKEND_URL="http://localhost:8000" BACKEND_API_KEY="your-secret-key" python -m scrapers.run_scraper --ingest
```

Run periodically every 30 minutes and ingest:

```bash
BACKEND_URL="http://localhost:8000" BACKEND_API_KEY="your-secret-key" python -m scrapers.run_scraper --ingest --interval 30
```

Environment variables used:

- `IDEALISTA_SEARCH_URL` or `IDEALISTA_SEARCH_HTML` or `IDEALISTA_HTML_PATH` — source HTML input
- `IDEALISTA_SOURCE_ID` — UUID for source to attach to scraped items
- `PROFESSIONECASA_SEARCH_URL` or `PROFESSIONECASA_SEARCH_HTML` or `PROFESSIONECASA_HTML_PATH` — Professionecasa HTML input
- `PROFESSIONECASA_SOURCE_ID` — UUID for the Professionecasa source
- `PROFESSIONECASA_FETCH_DETAIL_IMAGES` — set to `false` to skip opening each Professionecasa listing page for gallery images
- `PROFESSIONECASA_DETAIL_CONCURRENCY` — max concurrent Professionecasa detail page requests (defaults to `4`)
- `PROFESSIONECASA_DETAIL_TIMEOUT` — timeout, in seconds, for each Professionecasa detail page request (defaults to `15`)
- `PROFESSIONECASA_MAX_DETAIL_PAGES` — optional cap for detail page requests; `0` means all listings
- `SCRAPER_USER_AGENT` — User-Agent sent by the shared HTTP client
- `SCRAPER_TIMEOUT_SECONDS` — request timeout for shared providers
- `SCRAPER_MAX_RETRIES` — max retries for transient HTTP failures
- `SCRAPER_CONCURRENCY_PER_SOURCE` — concurrent requests per source
- `SCRAPER_REQUEST_DELAY_MIN_MS` and `SCRAPER_REQUEST_DELAY_MAX_MS` — conservative delay between requests
- `SCRAPER_MISSING_THRESHOLD` — reserved for missing/removal policy tuning
- `SCRAPER_REMOVAL_AFTER_HOURS` — hours before a missing listing can become removed
- `SCRAPER_DETAIL_TTL_HOURS` — detail page refresh TTL
- `SCRAPER_MAX_PAGES` — default listing page cap for shared providers; `0` means provider/CLI decides
- `SCRAPER_DRY_RUN` — when `true`, shared providers do not persist changes
- `BACKEND_URL` — backend base URL (defaults to `http://localhost:8000`)
- `BACKEND_API_KEY` — required when using `--ingest`; sent as the `X-API-KEY` header

Notes:

- The FastAPI backend already exposes `POST /properties` which accepts the normalized `PropertyCreate` payload.
- New source integrations should expose a `provider` object and keep parsing, HTTP, normalization, persistence, and lifecycle decisions separated.
- For production scheduling use a process manager, systemd timer, or the hosting provider's cron/worker features.
