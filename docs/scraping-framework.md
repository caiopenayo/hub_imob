# Scraping Framework

Este projeto trata scraping como sincronização de inventário imobiliário, não como scripts isolados.

## Arquitetura

- `scrapers/core/providers.py`: contrato de provider.
- `scrapers/core/http.py`: cliente HTTP async com timeout, retry, backoff, cookies de sessão e rate limiting conservador.
- `scrapers/core/engine.py`: discovery, deduplicação, enriquecimento, upsert, reconciliação e métricas.
- `scrapers/core/persistence.py`: persistência em `Property`, `PropertyPhoto`, `PropertyEvent` e `JobLog`.
- `scrapers/sources/zimoveis.py`: provider Zimmermann Imóveis.

Um provider deve conhecer apenas a fonte específica. Ele retorna `PropertyCandidate` e `PropertyDetail`; não deve importar models SQLAlchemy.

## Adicionar Uma Corretora

1. Crie `scrapers/sources/nova_fonte.py`.
2. Implemente uma classe que herde `RealEstateProvider`.
3. Defina `source_key`, `source_name`, `base_url` e `default_search_scope`.
4. Implemente `build_search_request`, `parse_listing_page` e, se houver detalhe, `parse_property_detail`.
5. Registre a key em `scrapers/core/registry.py`.
6. Crie seed/migration idempotente para `sources`.
7. Adicione fixtures HTML sanitizadas e testes sem internet.

## Executar Zimmermann Em Dry-Run

```bash
python3 -m scrapers.run_scraper \
  --source zimoveis \
  --search-q "Sao Paulo" \
  --mode delta \
  --dry-run \
  --max-pages 2 \
  --max-details 5 \
  --output-json /tmp/zimoveis-dry-run.json
```

## Executar Delta

```bash
python3 -m scrapers.run_scraper --source zimoveis --mode delta --max-pages 5 --max-details 20
```

Delta não executa reconciliação global de ausentes.

## Executar Full

```bash
python3 -m scrapers.run_scraper --source zimoveis --mode full --max-details 100
```

Full só reconcilia ausentes quando a execução termina com sucesso, sem erro HTTP/parsing crítico, sem `max_pages` de desenvolvimento e sem queda anormal de volume.

## Estados

- `ACTIVE`: anúncio visto na última execução aplicável.
- `MISSING`: anúncio não visto em full crawl completo.
- `REMOVED`: anúncio continuou ausente até atingir threshold configurado.

Se um anúncio `MISSING` ou `REMOVED` reaparece, ele volta para `ACTIVE` e gera evento `REACTIVATED`.

## Detalhes

Detalhes são revisitados quando:

- imóvel é novo;
- ainda não tem detalhe;
- hash da listagem mudou;
- TTL de detalhe expirou;
- modo `full` exige enriquecimento.

## Rate Limiting

Configure:

- `SCRAPER_TIMEOUT_SECONDS`
- `SCRAPER_MAX_RETRIES`
- `SCRAPER_CONCURRENCY_PER_SOURCE`
- `SCRAPER_REQUEST_DELAY_MIN_MS`
- `SCRAPER_REQUEST_DELAY_MAX_MS`
- `SCRAPER_DELTA_STALE_PAGES`
- `SCRAPER_MAX_INVALID_CARD_RATE`
- `SCRAPER_FULL_MIN_LISTING_RATIO`

## Migrations

```bash
cd backend
alembic upgrade head
```

## Testes

```bash
python3 -m pytest tests
```

Os testes de provider e sincronização usam fixtures e `httpx.MockTransport`; não fazem chamadas reais à internet.

## Limitações

- Seletores HTML podem mudar sem aviso.
- O worker atual usa FastAPI BackgroundTasks para MVP; produção em escala deve migrar para Celery, Dramatiq, RQ ou Arq.
- Imagens são armazenadas como URLs; download/proxy/cache ainda não foi implementado.
- A localização extraída de mapa público é aproximada.

## Quando O Site Mudar

1. Salve uma fixture sanitizada nova em `tests/fixtures`.
2. Atualize apenas o provider da fonte afetada.
3. Rode `python3 -m pytest tests/test_zimoveis_provider.py`.
4. Rode a suíte completa antes de publicar.
