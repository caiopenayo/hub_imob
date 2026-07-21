# Sale Scraping Scheduler

Esta camada transforma os providers existentes em uma operação agendada para imóveis `SALE` em São Paulo, SP. Ela não roda dentro do FastAPI: o processo dedicado é iniciado separadamente.

## Processo

```bash
python3 -m scrapers.scheduler
```

Para cron externo, rode somente os jobs vencidos e saia:

```bash
python3 -m scrapers.scheduler --run-due-once
```

Para ver os próximos schedules:

```bash
python3 -m scrapers.scheduler --list-schedules
```

## Estratégia

- Timezone dos schedules: `America/Sao_Paulo`.
- Persistência de datas continua seguindo a convenção atual do projeto: UTC naive no banco.
- Full crawl de venda: diário às 03:00, com offset por fonte.
- Health check: leve, a cada hora, sem persistir imóveis ou ofertas.
- Priority crawl: delta a cada 4 horas, com um job separado por provider e bairro confirmado.
- Providers sem filtro regional real registram o priority crawl como `skipped` e seguem apenas com full diário.

## Bairros Prioritários

Confirmados e ativos em `scrapers/core/sale_scope.py`:

- Pinheiros
- Vila Madalena
- Perdizes
- Pompeia
- Sumaré
- Butantã

A tradução desses bairros para URLs ou parâmetros do site pertence ao provider. O scheduler não filtra localmente para simular prioridade.

Padrões confirmados:

- Local Imóveis: `https://www.localimoveis.com.br/imoveis/venda/sp/sao-paulo/{bairro_slug}`
- Zimmermann: `https://www.zimoveis.com.br/buscar-imoveis?bairros={bairro_slug}`
- Pacheco: `https://pacheco.com.br/comprar/?cidades=72&...&bairro[]={bairro_id}&order=`

IDs Pacheco confirmados:

- Pinheiros: `138`
- Vila Madalena: `119`
- Perdizes: `137`
- Pompeia: `123`
- Sumaré: `132`
- Butantã: `139`

## Capabilities

Cada provider declara `ProviderCapabilities`:

- `supports_sale`
- `supports_city_scope`
- `supports_neighborhood_scope`
- `supports_detail`
- `supports_full_reconciliation`

O scheduler trabalha só com essa interface compartilhada.

## Locking

O processo usa PostgreSQL advisory locks:

- `{source}:sale:full_city:sao-paulo`
- `{source}:sale:priority_neighborhoods:sao-paulo`
- `{source}:sale:any:sao-paulo`

Dois jobs equivalentes não rodam ao mesmo tempo. Priority e health check são ignorados quando há crawl ativo para a mesma fonte.

## Detalhes e Fotos

O `SyncEngine` continua decidindo quando buscar detalhes. Para a operação de venda, o scheduler sobrescreve o TTL para 7 dias via `SALE_DETAIL_REFRESH_DAYS`.

Fotos não são baixadas nem validadas por `HEAD`. A sincronização preserva URLs e ordem, usando a lógica já existente de galeria.

## Missing e Removed

Runs `partial`, `failed`, com `max_pages`, queda suspeita ou erro de parser não reconciliam ausências. Apenas full city completo e válido pode marcar ausência.

Política inicial:

- primeira ausência em full válido: oferta `SALE` vira `MISSING`;
- segunda ausência em full válido: oferta `SALE` vira `REMOVED`;
- reaparecimento: oferta volta para `ACTIVE`.

## Configuração

Principais variáveis:

```env
SALE_SCRAPING_ENABLED=true
SALE_SCRAPING_TIMEZONE=America/Sao_Paulo
SALE_FULL_CRAWL_ENABLED=true
SALE_FULL_CRAWL_HOUR=3
SALE_FULL_CRAWL_SOURCE_OFFSET_MINUTES=15
SALE_FULL_CRAWL_JITTER_MINUTES=10
SALE_PRIORITY_CRAWL_ENABLED=true
SALE_PRIORITY_CRAWL_HOURS=2,6,10,14,18,22
SALE_PRIORITY_SOURCE_OFFSET_MINUTES=10
SALE_PRIORITY_JITTER_MINUTES=10
SALE_HEALTH_CHECK_ENABLED=true
SALE_HEALTH_CHECK_INTERVAL_MINUTES=60
SALE_DETAIL_REFRESH_DAYS=7
SALE_MISSING_RUNS_BEFORE_REMOVAL=2
SALE_MINIMUM_INVENTORY_RATIO=0.70
```

`SALE_MAX_PAGES=0` e `SALE_MAX_DETAILS=0` significam sem limite operacional. Para desenvolvimento, passe limites por CLI.

## Execução Manual

Health check:

```bash
python3 -m scrapers.scheduler --provider pacheco --job-type sale_health_check
```

Priority crawl:

```bash
python3 -m scrapers.scheduler --provider pacheco --job-type sale_priority_crawl --dry-run --max-pages 1
```

Hoje esse job usa Pinheiros nos providers reais. Outros bairros só entram depois que tivermos URLs ou IDs confirmados por provider.

Full dry-run limitado:

```bash
python3 -m scrapers.scheduler --provider pacheco --job-type sale_full_crawl --dry-run --max-pages 2 --max-details 2
```

Também funciona pela CLI existente:

```bash
python3 -m scrapers.run_scraper --provider pacheco --job-type full-crawl --dry-run --max-pages 2 --max-details 2
```

## API Administrativa

Endpoints protegidos por `X-API-KEY`:

- `GET /scrape/schedules`
- `POST /scrape/schedules/run`

Exemplo:

```json
{
  "provider": "pacheco",
  "job_type": "sale_health_check",
  "dry_run": true
}
```

## Deploy

Processo dedicado:

```bash
python3 -m scrapers.scheduler
```

Cron externo:

```bash
python3 -m scrapers.scheduler --run-due-once
```

Docker:

```bash
docker build -f scrapers/Dockerfile -t imob-scheduler .
docker run --env-file .env imob-scheduler
```

## Troubleshooting

- Se priority crawl aparece como `skipped`, o provider não declarou filtro regional server-side.
- Se full crawl fica `partial`, veja `summary.stopped_reason`.
- Se jobs não disparam, confira `SALE_SCRAPING_ENABLED` e `--list-schedules`.
- Se houver erro `No module named scrapers`, inicie o backend/scheduler a partir da raiz do repositório com `backend.app.main:app`.
