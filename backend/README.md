# Backend

## Busca em linguagem natural

O backend possui uma primeira versão completa para transformar texto livre do usuário em um contrato validado chamado `SearchIntent`, normalizar esse contrato contra o inventário real e executar uma busca determinística com SQLAlchemy.

O fluxo de segurança é:

```text
texto do usuário
  ↓
modelo local ou API remota de inferência
  ↓
candidato SearchIntent não confiável
  ↓
JSON parsing
  ↓
validação Pydantic com schema fechado
  ↓
normalização de negócio contra inventário ativo
  ↓
query builder determinístico e parametrizado
  ↓
PostgreSQL
```

O modelo não acessa o banco, não recebe URL do banco, não recebe chaves do Supabase, não tem ferramenta para executar SQL, não chama URLs arbitrárias e não modifica estado da aplicação. Quando a inferência roda no Colab, o backend envia apenas o texto da busca para a API remota. A saída do modelo é sempre tratada como dado não confiável.

Endpoint:

```bash
curl -X POST http://localhost:8000/search/intent \
  -H "Content-Type: application/json" \
  -d '{"query":"apartamento em Pinheiros até 1 milhão com 2 quartos"}'
```

Também existem dois endpoints públicos para a próxima camada:

```bash
curl -X POST http://localhost:8000/search/interpret \
  -H "Content-Type: application/json" \
  -d '{"query":"Quero um apartamento de 100 m² em Pinheiros por até 1 milhão"}'
```

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query":"Quero um apartamento de uns 100 m² em Pinheiros por até 1 milhão","page":1,"per_page":20}'
```

O fluxo operacional resumido é:

```text
query -> SearchIntent -> normalização determinística -> SQLAlchemy query -> ranking determinístico
```

O LLM não acessa o banco, não gera SQL e não decide se um bairro existe. A normalização usa cidades e bairros já presentes no inventário ativo.

## Normalização e ranking

A normalização faz:

- limpeza de espaços;
- comparação sem acentos e sem diferenciar maiúsculas/minúsculas;
- aliases explícitos como `sp` para `São Paulo`;
- validação de bairro contra cidade;
- fuzzy match apenas com limiar alto;
- exposição de `normalization_issues` quando algo não é seguro.

Critérios obrigatórios viram filtros SQLAlchemy parametrizados. Critérios `preferred` não entram no `WHERE`; eles afetam `match_score`, `matched_preferences`, `missing_preferences` e `unknown_preferences`.

Valores aproximados usam tolerância inicial de 10%:

```env
SEARCH_PRICE_TARGET_TOLERANCE=0.10
SEARCH_AREA_TARGET_TOLERANCE=0.10
SEARCH_MAX_PER_PAGE=50
SEARCH_LOG_RAW_QUERY=false
```

Dados booleanos, como varanda, usam três estados: `true`, `false` e `null`. Registros antigos continuam como `null`; isso significa desconhecido, não `false`.

Para aplicar o campo `balcony` no banco:

```bash
cd backend
alembic upgrade head
```

## Configuração do modelo local

O modelo local é configurado por ambiente:

```env
SEARCH_LLM_ENABLED=true
SEARCH_LLM_PROVIDER=local_huggingface
SEARCH_LLM_MODEL_ID=Qwen/Qwen2.5-0.5B-Instruct
SEARCH_LLM_REVISION=
SEARCH_LLM_DEVICE=auto
SEARCH_LLM_MAX_INPUT_TOKENS=1024
SEARCH_LLM_MAX_NEW_TOKENS=192
SEARCH_LLM_TIMEOUT_SECONDS=180
SEARCH_LLM_MAX_CONCURRENCY=1
SEARCH_LLM_MAX_QUERY_CHARACTERS=500
SEARCH_LLM_LOAD_FAILURE_COOLDOWN_SECONDS=300
```

`SEARCH_LLM_DEVICE=auto` usa CUDA quando disponível e CPU caso contrário. Para forçar CPU:

```env
SEARCH_LLM_DEVICE=cpu
```

Para computadores com pouca memória, comece com:

```env
SEARCH_LLM_MODEL_ID=Qwen/Qwen2.5-0.5B-Instruct
```

Modelos maiores podem melhorar a extração, mas devem ser validados pelo benchmark antes de virarem padrão.

Para forçar GPU:

```env
SEARCH_LLM_DEVICE=cuda
```

No primeiro uso, o Hugging Face baixa tokenizer e pesos do modelo. Por padrão, esses arquivos ficam no cache local do Hugging Face, normalmente em `~/.cache/huggingface`. Em produção, esse cache deve ficar em disco persistente ou ser preparado na imagem/container para evitar download a cada deploy.

O carregamento é preguiçoso: o modelo só é carregado na primeira chamada e é reutilizado no mesmo processo. A inferência roda fora do event loop do FastAPI e tem concorrência limitada por `SEARCH_LLM_MAX_CONCURRENCY`.

Se o carregamento falhar, a falha fica em cache por `SEARCH_LLM_LOAD_FAILURE_COOLDOWN_SECONDS` para evitar retries caros a cada requisição. Timeouts e erro de CUDA out-of-memory viram erro 503 sanitizado nos endpoints públicos.

## Inferência remota no Colab

Para rodar tokenizer/modelo em uma GPU do Google Colab, use:

```env
SEARCH_LLM_ENABLED=true
SEARCH_LLM_PROVIDER=remote_http
SEARCH_LLM_REMOTE_URL=https://SEU-TUNNEL.trycloudflare.com
SEARCH_LLM_REMOTE_API_KEY=troque-este-token
SEARCH_LLM_REMOTE_GENERATE_PATH=/generate
SEARCH_LLM_REMOTE_REPAIR_PATH=/repair
SEARCH_LLM_REMOTE_REPAIR_ENABLED=true
SEARCH_LLM_MODEL_ID=Qwen/Qwen2.5-1.5B-Instruct
SEARCH_LLM_TIMEOUT_SECONDS=180
SEARCH_LLM_MAX_NEW_TOKENS=192
```

Nesse modo, o frontend continua chamando somente o FastAPI local. O Colab recebe apenas `query` em `/generate`, e apenas `malformed_output`/`validation_error` truncados em `/repair`. Ele não recebe dados de imóveis, banco, Supabase, leads, telefone, e-mail nem SQL.

Guia com células prontas para Colab: [docs/colab-search-inference.md](../docs/colab-search-inference.md).

Para desativar a busca natural sem derrubar os endpoints tradicionais:

```env
SEARCH_LLM_ENABLED=false
```

Nesse modo, `/properties` continua funcionando e `/search` retorna indisponibilidade controlada.

## Health, readiness e status do modelo

Checks disponíveis:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl http://localhost:8000/health/search-model
```

`/health` é liveness leve e não acessa banco nem modelo. `/ready` checa o banco com `SELECT 1` e não carrega o modelo. `/health/search-model` retorna apenas estado operacional do provider configurado. Para modelo local, pode retornar `disabled`, `unloaded`, `loading`, `ready` ou `failed`; para Colab remoto, retorna `configured` ou `unconfigured` sem fazer chamada externa.

As respostas não expõem caminhos internos do filesystem, secrets, cookies ou stack traces.

## Benchmark de intenção de busca

Existe uma fixture versionada com mais de 50 buscas representativas em português brasileiro:

```text
tests/fixtures/search_intent_cases.json
```

Ela cobre compra, aluguel, bairros, cidades, faixas de preço, área, quartos, banheiros, vagas, varanda, critérios obrigatórios/preferenciais, ambiguidades e casos adversariais.

Para executar a avaliação com o modelo real configurado:

```bash
python3 backend/scripts/evaluate_search_intent_model.py --limit 10
```

Para salvar um relatório JSON:

```bash
python3 backend/scripts/evaluate_search_intent_model.py \
  --json-report /tmp/search-intent-report.json
```

Esse benchmark pode baixar/carregar o modelo real. Ele não roda na suíte unitária padrão.

## Quality gates iniciais

Metas práticas para considerar uma troca de prompt/modelo saudável:

- `valid JSON >= 95%`;
- `valid SearchIntent >= 90%`;
- `simple-case field accuracy >= 90%`;
- zero ações arbitrárias de banco;
- zero execução de SQL vindo do modelo;
- zero exposição de secrets.

Os números devem ser medidos pelo runner, não ajustados manualmente.

## Limitações

O modelo pequeno pode errar extrações em frases ambíguas. Por isso a saída passa por parsing defensivo, schema fechado com Pydantic e uma única tentativa controlada de reparo. Campos desconhecidos são rejeitados.

Essa implementação não usa quantização. Quantização com bibliotecas como `bitsandbytes` pode ser adicionada depois, se fizer sentido para custo e memória.

O projeto foca principalmente anúncios de venda, mas o interpretador não infere `sale` automaticamente. Se quisermos venda como padrão do produto, isso deve ser aplicado depois, na camada determinística de negócio.

Busca em linguagem natural ainda não é conversa, negociação ou diagnóstico avançado. Quando o inventário não conhece uma feature, ela permanece desconhecida. Critérios de relaxamento automático e perguntas de follow-up ainda são próximos passos.

## Testes

Testes normais, com o modelo mockado:

```bash
python3 -m pytest tests/test_search_intent.py tests/test_natural_search.py tests/test_search_operational_safety.py tests/test_search_intent_benchmark.py
```

Smoke test opcional com modelo real local:

```bash
RUN_LOCAL_MODEL_TESTS=1 python3 -m pytest tests/test_search_intent.py -m local_model
```

Esse teste real pode baixar o modelo e requer memória suficiente para carregar `SEARCH_LLM_MODEL_ID`.

Para rodar tudo:

```bash
python3 -m pytest tests
```

## Frontend

O frontend chama `POST /search` pelo `NEXT_PUBLIC_API_URL`. Quando o backend retorna 503 por modelo indisponível, a tela mantém os filtros tradicionais disponíveis. O frontend não recebe tokens Hugging Face, chaves Supabase ou configuração sensível do backend.
