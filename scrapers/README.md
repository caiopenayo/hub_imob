# Scrapers

This folder contains simple scrapers that normalize property listings and either return the results or ingest them into the FastAPI backend.

Quick run examples:

Run single source (default `idealista`) and print results:

```bash
python -m scrapers.run_scraper
```

Run a provider implemented with the shared sync framework in dry-run mode:

```bash
python -m scrapers.run_scraper --source zimoveis --dry-run --mode delta --search-q "Sao Paulo" --max-pages 2 --max-details 5
```

Run Local Imóveis in dry-run mode:

```bash
python -m scrapers.run_scraper \
  --provider localimoveis \
  --mode delta \
  --state sp \
  --city sao-paulo \
  --purpose sale \
  --max-pages 2 \
  --max-details 3 \
  --dry-run
```

Run a provider and persist changes directly to the database:

```bash
python -m scrapers.run_scraper --source zimoveis --mode full --max-pages 10
```

Persist a limited Local Imóveis delta run:

```bash
python -m scrapers.run_scraper \
  --provider localimoveis \
  --mode delta \
  --state sp \
  --city sao-paulo \
  --purpose sale \
  --max-pages 2 \
  --max-details 3
```

Run Pacheco in dry-run mode for sale or rent:

```bash
python -m scrapers.run_scraper \
  --provider pacheco \
  --purpose sale \
  --mode delta \
  --max-pages 2 \
  --max-details 2 \
  --dry-run

python -m scrapers.run_scraper \
  --provider pacheco \
  --purpose rent \
  --mode delta \
  --max-pages 1 \
  --max-details 2 \
  --dry-run
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
- `SCRAPER_USER_AGENT` — User-Agent sent by the shared HTTP client
- `SCRAPER_TIMEOUT_SECONDS` — request timeout for shared providers
- `SCRAPER_MAX_RETRIES` — max retries for transient HTTP failures
- `SCRAPER_CONCURRENCY_PER_SOURCE` — concurrent requests per source
- `SCRAPER_REQUEST_DELAY_MIN_MS` and `SCRAPER_REQUEST_DELAY_MAX_MS` — conservative delay between requests
- `SCRAPER_MISSING_THRESHOLD` — reserved for missing/removal policy tuning
- `SCRAPER_REMOVAL_AFTER_HOURS` — hours before a missing listing can become removed
- `SCRAPER_DETAIL_TTL_HOURS` — detail page refresh TTL
- `SCRAPER_DELTA_STALE_PAGES` — consecutive stale listing pages before delta crawl stops
- `SCRAPER_MAX_INVALID_CARD_RATE` — marks a run partial when too many cards fail to parse
- `SCRAPER_FULL_MIN_LISTING_RATIO` — blocks removals when a full run sees an abnormally low inventory
- `SCRAPER_MAX_PAGES` — default listing page cap for shared providers; `0` means provider/CLI decides
- `SCRAPER_DRY_RUN` — when `true`, shared providers do not persist changes
- `BACKEND_URL` — backend base URL (defaults to `http://localhost:8000`)
- `BACKEND_API_KEY` — required when using `--ingest`; sent as the `X-API-KEY` header

Notes:

- The FastAPI backend already exposes `POST /properties` which accepts the normalized `PropertyCreate` payload.
- New source integrations should expose a `provider` object and keep parsing, HTTP, normalization, persistence, and lifecycle decisions separated.
- For production scheduling use a process manager, systemd timer, or the hosting provider's cron/worker features.

## Provider architecture notes

Providers implement only source-specific behavior: request construction, listing parsing, detail parsing and normalization into DTOs. The shared `SyncEngine` handles discovery, deduplication, detail TTL, persistence, lifecycle and run metrics. To add another real estate source, create `scrapers/sources/<key>.py`, expose a `provider` object, add tests with local HTML fixtures and register the key in `scrapers/core/registry.py`.

## Local Imóveis

- Source key: `localimoveis`
- Base URL: `https://www.localimoveis.com.br`
- Supported listing paths: `/imoveis/venda/{state_slug}/{city_slug}` and `/imoveis/locacao/{state_slug}/{city_slug}`
- Pagination: follows `rel=next`/next URL from the HTML and stops on empty, repeated or limited pages.
- Images may be hosted under `betaimages.lopes.com.br`; this is only an image host signal and does not change `source_id`.
- The provider stores `metadata_json["reo_reference"]` when available, but does not merge records across Lopes or other sources.

Local Imóveis can expose sale and rent prices for the same external listing. The database keeps one `Property` per `(source_id, external_id)` and stores prices in `property_offers`:

- `SALE` and `RENT` are upserted independently.
- `properties.price`, `price_currency` and `transaction_type` remain as legacy mirror fields for frontend compatibility.
- When a crawl is scoped to sale, full reconciliation only marks the `SALE` offer as missing/removed; `RENT` is preserved.
- A `Property` remains `ACTIVE` while at least one offer is active.

Detail pages are revisited only when the property is new, details are missing, listing hash changes, the detail TTL expires, full mode requests enrichment, or an offer change justifies revalidation. The scraper stores image URLs and photo order; it does not download or validate each image.

Full runs reconcile missing/removal only when the run is complete and healthy. Runs stopped by `max_pages`, repeated pagination, HTTP errors, parse-error thresholds, or suspiciously low totals are marked partial and do not remove properties or offers.

To refresh fixtures after an HTML change, save sanitized listing/detail HTML under `tests/fixtures/localimoveis/`, update parser tests first, then run:

```bash
python -m pytest tests/test_localimoveis_provider.py tests/test_localimoveis_sync_integration.py
```

## Pacheco Imóveis

- Source key: `pacheco`
- Base URL: `https://pacheco.com.br`
- Sale discovery: `/comprar/`, `/comprar/page/{n}/`
- Rent discovery: `/alugar/`, `/alugar/page/{n}/`
- Identity: `(source_id, external_id)`, preserving prefixes such as `Z-268289`, `V1-51824` and `L1-50943`.
- HTTP mode: server-rendered HTML through the shared `httpx` client. No browser automation, copied cookies or private API calls.

Pacheco sale and rent are independent crawl scopes. A sale crawl upserts only the `SALE` offer, and a rent crawl upserts only the `RENT` offer. If the same `external_id` appears in both scopes, the shared persistence layer keeps one `Property` and separate `property_offers` rows. If the prefixes differ, the records remain distinct; `Z-268289`, `V1-268289` and `L1-268289` are not merged. WordPress post IDs, PI references and Vista numeric IDs are stored only as metadata signals.

The provider follows HTML pagination and uses card IDs, detail URLs and the detail page identity block as authority. Pacheco JSON files such as `/json/imoveis-venda.json` and `/json/imoveis-alugar.json` are not used for discovery, persistence, reconciliation or removal because they do not carry a stable public listing identity.

Cards can already contain multiple photos. For a new property, those listing images are persisted as the initial gallery if the detail page is not fetched. When a valid detail page is fetched, the main hero gallery reconciles photos while preserving order and inactivating missing detail photos. Images are not downloaded or individually validated.

Rent details keep monthly values separate: the `RENT` offer price is the advertised rent, while IPTU period, condominium fee and advertised monthly total remain in structured metadata. For example, `L1-50943` persists rent `10000.00`, monthly IPTU `467.15` and advertised monthly total `10467.15`.

Use `POST /scrape` with provider-backed payloads:

```json
{
  "source_keys": ["pacheco"],
  "mode": "delta",
  "scope": {"purpose": "sale"},
  "max_pages": 2,
  "max_details": 2,
  "dry_run": false
}
```

Full runs reconcile missing offers only when the run is complete and healthy. Runs stopped by `max_pages`, repeated pagination, parse failures, HTTP errors or suspicious inventory drops are marked partial and do not mark offers missing or removed.

To refresh Pacheco fixtures after an HTML change, save sanitized listing/detail HTML under `tests/fixtures/pacheco/`, update parser tests first, then run:

```bash
python -m pytest tests/test_pacheco_provider.py tests/test_pacheco_sync_integration.py
```

## Dedicated Sale Scheduler

The initial production operation for São Paulo sale listings runs outside FastAPI:

```bash
python3 -m scrapers.scheduler
```

List registered schedules:

```bash
python3 -m scrapers.scheduler --list-schedules
```

Run due jobs once for external cron:

```bash
python3 -m scrapers.scheduler --run-due-once
```

Run a limited full dry-run manually:

```bash
python3 -m scrapers.scheduler \
  --provider pacheco \
  --job-type sale_full_crawl \
  --dry-run \
  --max-pages 2 \
  --max-details 2
```

The scheduler uses `America/Sao_Paulo`, stable per-source offsets, jitter, PostgreSQL advisory locks, health checks, and provider capabilities. Priority neighborhood crawls run as separate jobs for the confirmed São Paulo neighborhoods: Pinheiros, Vila Madalena, Perdizes, Pompeia, Sumaré and Butantã. See `docs/sale-scheduler.md`.
