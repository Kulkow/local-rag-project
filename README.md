# Enterprise RAG Platform

Docker-first reference project, Phase 1: FastAPI, async PostgreSQL, Alembic,
Celery/Redis, Qdrant, MinIO, host-installed Ollama and Vue 3/Vite/PrimeVue 4/Pinia administration.
Database-backed users, family administration and service monitoring are implemented.
Document upload and queued PDF extraction/chunking/embedding indexing are implemented.
Advanced RAG is implemented: PostgreSQL FTS + vector hybrid retrieval, RRF,
optional local LLM reranking, ACL-filtered evidence and cited local answers.
Agent workflows and quality evaluation remain future phases.

## Start

Docker Engine with Compose v2 and a running host-installed Ollama are required.
The root configuration is `docker-compose.yaml`; `docker compose` finds it automatically.
CPU operation is the default.
Plan for 16 GB RAM (at least 10 GB allocated to Docker) and 20 GB free disk.
Initial builds and model downloads require internet access.

```sh
cp -n .env.example .env
# Edit .env: set POSTGRES_PASSWORD, MINIO_ROOT_USER, MINIO_ROOT_PASSWORD,
# ADMIN_USERNAME, ADMIN_PASSWORD and a separate random JWT_SECRET to your own values.
# Use URL-safe random PostgreSQL passwords; MinIO password must be >=8 characters.
make lock
docker compose config --quiet
docker compose up -d --build
make bootstrap-admin
docker compose ps
make smoke
```

Web Admin: http://localhost:3000 — after `make bootstrap-admin`, sign in with
ADMIN_USERNAME and ADMIN_PASSWORD to check live services. API/OpenAPI: http://localhost:8000/docs. MinIO: http://localhost:9001.
Browser API calls use Nginx `/api`; no cross-origin CORS access is enabled.
Container ports bind only to localhost. Databases and object API are internal.
Ollama runs on the host; containers use `host.docker.internal:11434`.
No default administrator credentials are supplied. `.env` is ignored by Git.

Migrations run once through the `migrate` service before API/worker startup.
For later schema updates run `make migrate`. Do not delete named volumes to upgrade.
`docker compose down` preserves data. Rotate database user passwords through the
Users page. Environment Basic credentials for `/ready` rotate separately by editing
`.env` and recreating API/worker (`docker compose up -d --force-recreate api worker`).
Changing PostgreSQL/MinIO credentials for existing volumes needs service-specific
credential rotation; editing environment variables alone does not rotate stored users.
Use TLS and real session management before exposing this local reference remotely.

## Verification

```sh
curl -fsS http://localhost:8000/health
# curl prompts for password, avoiding it in shell history:
curl -i -u YOUR_ADMIN_USERNAME http://localhost:8000/ready
make check
make smoke
docker compose exec worker celery -A app.infrastructure.queue.tasks:celery_app inspect ping
```

`/health` is public liveness. `/ready` requires server-validated admin credentials,
returns 200 when all five dependencies are available, otherwise 503 with boolean
service states. Database readiness requires the migration marker. Request responses
include X-Request-ID and Server-Timing. Logs contain JSON request metadata without
credentials, prompts, query strings or document contents. Worker health is checked
separately using Celery; readiness does not claim worker or model inference health.

`make check` runs Ruff lint/format, strict mypy, pytest (including an actual migrated
PostgreSQL integration test), frontend API tests, TypeScript and Vite build in Docker.
Normal unit tests need no model. CI uses Docker and an isolated PostgreSQL database.
Direct dependencies are pinned. This environment could not reach PyPI/npm to generate
lockfiles. Before the first reproducible build run `make lock` (Docker only), review
and commit `uv.lock` and `web-admin/package-lock.json`. Builds without those files
bootstrap dependency resolution and are not yet fully reproducible. Once generated,
Python sync uses the lock and npm uses `npm ci`.
Regenerate frontend schemas after API changes:

```sh
docker compose --profile tools run --rm -v "$PWD/web-admin:/app/web-admin" checks uv run --frozen python scripts/export_openapi.py
docker compose --profile tools run --rm -v "$PWD/web-admin:/contract" web-checks npx openapi-typescript /contract/openapi.json -o /contract/src/shared/infrastructure/schema.ts
```

## Models

The local model store contains `qwen3:4b` and `embeddinggemma:latest`.
These are selected in `.env` and `.env.example`. Availability was confirmed from
local manifest files; embedding inference is now covered by the ingestion smoke test; chat inference has not been tested.

```sh
ollama list
# Start Ollama using the installed application, or if no server is already running:
ollama serve
# In another terminal, verify the host API:
curl -fsS http://localhost:11434/api/tags
```

`make models` lists the host's installed models and does not download anything.
The Compose stack does not start or manage an Ollama container. Stop/start of the
stack preserves the existing host model store. API readiness probes the configured
`OLLAMA_URL`; model selection is configuration for subsequent ingestion/answering
phases and does not yet trigger inference. Embedding dimensions are validated during ingestion.

On Docker Desktop for macOS, containers connect through `host.docker.internal`.
If the API reports Ollama unavailable, check connectivity from a container:

```sh
docker compose run --rm --no-deps api python -c 'import os,httpx; r=httpx.get(os.environ["OLLAMA_URL"]+"/api/tags",timeout=5); r.raise_for_status(); print(r.json())'
```

A host Ollama bound only to loopback may need its listen address configured to
accept Docker traffic. For a manually launched server, use
`OLLAMA_HOST=0.0.0.0:11434 ollama serve` after stopping the existing server, and
restrict inbound access with the host firewall: Ollama has no application-level
authentication. For a managed application, configure its server environment instead.
Linux also requires a reachable listen address; the Compose host-gateway mapping
provides the hostname. Set `OLLAMA_URL` in `.env` if using another address.

Hardware acceleration is managed by the host Ollama installation. No GPU device
mapping is needed in Compose. Model performance has not been measured.

## Layout and limitations

Backend is organized by DDD modules under `src/app/modules`:
`families/domain` owns family entities and relationship rules;
`families/infrastructure` owns SQLAlchemy mappings;
`operations/application` owns readiness orchestration and probe ports;
`operations/infrastructure` implements probes, and `operations/api` exposes HTTP.
`main.py` composes adapters, `api/security.py` handles local HTTP authentication,
`core` contains settings, and shared `infrastructure` contains the engine and Celery.
`migrations` owns schema history; `web-admin` remains the Vue SPA.
See [ADR 0005](docs/adr/0005-ddd-modules.md) for module boundaries and dependencies.

Local verification in the authoring environment is recorded below. Full stack startup
requires Docker socket access; do not interpret generated configuration as a measured
production result. Observability services remain outside the critical startup path.

## Authoring environment verification

- `docker compose config --quiet`: passed with explicitly supplied configuration.
- `python3 -m compileall -q src migrations tests scripts`: passed.
- Docker daemon access: denied by the environment; stack, migrations, database
  integration and container health checks could not be run.
- PyPI/npm DNS resolution: unavailable; lock generation, Ruff, mypy, pytest and
  frontend build/tests could not be completed here. Run `make lock`, `make up`,
  `make check` and `make smoke` on a Docker-capable machine with network access.
- `.env` was initialized locally with random credentials and is not a tracked file.

## Python deprecation checks

`make lint-python` runs the pinned Ruff version against application code, migrations,
scripts and tests without starting dependent services. Rules include pyupgrade (`UP`)
with Python 3.12 as the explicit target, including deprecated imports (`UP035`).
The same settings apply to `make check`, CI and pre-commit. These checks cover
known Python patterns, not every third-party library's deprecated API or package
support lifecycle. Full checks also run strict mypy.

The authoring environment could not install Ruff (PyPI DNS unavailable) or run
Docker (socket access denied). A limited AST scan of known legacy imports and
API calls and Python 3.12 syntax compilation found no matches/errors; this does
not constitute a successful Ruff or mypy run.

## MinIO image availability

The old `minio/minio` Docker Hub image may return `pull access denied` even without
any local authentication problem. Quay availability is also not assumed. Compose
now builds `enterprise-rag-minio:local` using `infra/minio/Dockerfile`, from upstream
release `RELEASE.2024-12-18T13-15-44Z`, commit
`16f8cf1c52f0a77eeb8f7565aaf7f7df12454583`. The existing storage version and volume
are retained; no replacement storage engine or data migration is introduced.

```sh
docker compose build minio
docker compose up -d --build
docker compose ps
# Once API is running and healthy:
make smoke
```

The first build compiles Go source and can take several minutes; GitHub, Docker Hub
(base Go/Alpine images), Alpine package repositories and Go module servers must be
reachable. Go dependencies are checked against upstream go.sum. The build supports
the Docker host architecture, including ARM64. MinIO runs as UID 10001 and exposes a
readiness healthcheck before the API starts. Existing volumes previously written by
another UID may require a deliberate ownership adjustment; do not delete the volume.
This preserves an old reference-project release, not an assertion that it is current
or security-maintained. Upstream repository is archived; see ADR 0003.

`service "api" is not running` from `make smoke` is a secondary error when startup
failed earlier. Resolve the build/startup error first. Useful diagnostics:
`docker compose logs --tail=100 minio migrate api`. Do not run `down -v` to fix a pull
error. Local source build and runtime remain unverified in the authoring sandbox
because Docker socket access is denied.

## Family data schema

Migration `0002` adds `families`, `persons`, `family_members`,
`person_relationships`, `pets` and `pet_owners`, with UUID keys, foreign keys,
uniqueness checks and timestamp triggers. These records are separate from
administrator authentication. Family and user HTTP endpoints are described in
[the API guide](docs/api/families-and-users.md).
See [ADR 0004](docs/adr/0004-user-role.md) for relationship direction, nullable
fields and deletion rules. Families with pets cannot be deleted until those pets
are explicitly moved or deleted. Existing people survive family deletion.

Apply with `docker compose build migrate && make migrate`. The integration test
`tests/integration/test_family_schema.py` uses synthetic records inside a rolled-back
transaction and requires `TEST_DATABASE_URL` pointing to a migrated database.

Schema 0002 was applied to the local PostgreSQL 16 instance; the database reports
revision `0002` and all six tables.

DDD refactoring verification: Ruff lint and formatting passed; strict mypy passed
for all 25 source files. Docker pytest completed with 19 passed and 1 skipped;
the skipped Compose packaging test requires a Docker CLI inside the checks image
and passed separately on the host using
`python3 -m unittest discover -s tests/unit -p test_compose.py`.
Tests include real PostgreSQL constraints, domain-to-ORM round trips, layer import
boundaries, readiness failures/timeouts/cancellation and the existing HTTP contract.
No database schema change is required for the module refactoring.
Rebuild the API and worker to use the new code: `docker compose up -d --build api worker`.

## Users and family administration

Database-backed authentication and family management are now available. After
building the updated images, run `make migrate` and `make bootstrap-admin` explicitly.
Bootstrap reads your ADMIN_USERNAME/ADMIN_PASSWORD, requires a password of at least
12 characters and never resets an existing user. Sign in at
http://localhost:3000/families to create a family and members, then open
http://localhost:3000/users to create accounts linked to those members.

System roles are admin (all families/accounts), manager (own family management),
and member (own family read only). The account has one unique family_member_id;
family roles such as parent do not grant application permissions. JWT access tokens expire
in eight hours and are stored by Pinia in localStorage. On reload, /auth/me
validates the saved token before granting UI access. Logout or user changes
revoke all their JWTs through users.token_version. JWT_SECRET is required. The dashboard also uses database login; environment
HTTP Basic remains available only to `/ready` and smoke checks.

See [setup and API guide](docs/api/families-and-users.md) and
[ADR 0006](docs/adr/0006-identity-family-access.md) for commands, rotation,
authorization rules, limitations and the frontend dependency audit findings.

Local verification of identity/family administration: Python lint/format/mypy
passed; pytest 25 passed, 1 skipped (Compose packaging passed separately on host).
Frontend 14 tests, TypeScript and Vite build passed. Updated API/worker/Web Admin
containers are healthy. Nginx-proxied login, authorized reads, readiness, logout
and rejection of the revoked token were verified. Visual browser QA was unavailable.


JWT authentication replaces server-side auth sessions; see
[ADR 0007](docs/adr/0007-jwt-pinia.md). Set a distinct random JWT_SECRET in .env,
apply migration 0004 and rebuild API/worker/Web Admin. The local key was generated
without logging its value. Old opaque access tokens require a new login.

JWT update verification: Ruff lint/format and mypy passed; Python pytest 35 passed,
1 skipped (Compose CLI test passed separately). Frontend 19 tests, TypeScript and
Vite build passed. Updated containers are healthy. Nginx checks verified signed
JWT login, rejection of a tampered signature and revocation of both issued tokens
on logout. localStorage restoration is covered by component tests; visual browser
QA was unavailable.

## Document upload for RAG

Модель хранения: [метаданные документов](docs/architecture/document-metadata.md) —
таблицы, ER-диаграмма, состояния, доступ и связь с объектами MinIO.

Open http://localhost:3000/documents. Any authenticated user with access to a family can upload a PDF,
DOCX or UTF-8 HTML file up to 10 MiB, with private or family visibility. Originals
are stored in MinIO and metadata/checksum/upload status in PostgreSQL (migration
0005). Members can view accessible document metadata. JWT/Pinia login is reused.

**Uploaded documents are not indexed yet.** PDF text extraction now runs through
the processing queue described below, followed by chunks and embedding indexing. Authorized RAG search/answering are described in the RAG section below.
POST /documents accepts a raw binary body with Idempotency-Key; safe retries reuse
the original record. See [upload/API guide](docs/api/document-upload.md) and
[DDD/TDD ADR](docs/adr/0008-document-upload.md).

Build the updated API and Web Admin, run `make migrate`, then start the services.
Local MinIO credentials are passed from the existing environment; no new secrets
are committed. DOCUMENTS_BUCKET defaults to rag-documents. Live object-storage
checks are opt-in with TEST_OBJECT_STORAGE=1; ordinary unit tests need no LLM.

Upload verification: TDD red/green is recorded in ADR 0008. Ruff lint/format and
mypy passed; Python pytest with live MinIO enabled: 55 passed, 1 skipped (Compose
CLI test passed separately on host). Frontend: 27 tests and production build passed.
The API → PostgreSQL → MinIO test verified exact original bytes. Updated containers
are healthy; the documents page and protected API were checked through Nginx.
Visual browser QA was unavailable.

### Automatic PDF preparation from the upload form

PDF upload now commits a durable processing job with its metadata. Web Admin uses
`POST /documents/{id}/process` to confirm/retry scheduling, without waiting for
text extraction. Refresh the document list to see status and use «Просмотреть текст»
after success. DOCX/HTML currently remain stored without extraction. See the queue
section below for worker startup, Grafana and failure recovery.

Document metadata lifecycle rules are implemented in the immutable `Document` and
`Extraction` entities. PostgreSQL adapters use these transitions together with
conditional updates for concurrency protection; MinIO stores original and extracted
bytes. See [ADR 0010](docs/adr/0010-document-domain-lifecycle.md) for invariants and
[the data model](docs/architecture/document-metadata.md) for fields and constraints.

## Очередь обработки и Grafana (один обработчик)

PDF после успешной загрузки атомарно получает задание в PostgreSQL. Worker
последовательно извлекает текст через Celery/Redis: concurrency=1, prefetch=1,
одна реплика и embedded beat. DOCX/HTML пока только сохраняются.
Доступ проверяется повторно при выполнении. После извлечения создаются чанки и
эмбеддинги; API ответов доступен через /rag/ask.

```sh
docker compose build api
make migrate
docker compose up -d --build api worker web-admin
# Необязательно: отдельные Grafana credentials в .env; иначе используются
# уже заданные ADMIN_USERNAME/ADMIN_PASSWORD. Общих паролей по умолчанию нет.
docker compose --profile monitoring up -d --build queue-metrics prometheus grafana
```

Grafana: http://localhost:3001/d/document-processing — dashboard `Document Processing Queue`
в папке RAG. Datasource Prometheus и панели устанавливаются автоматически.
При первом запуске используются GRAFANA_ADMIN_USER/GRAFANA_ADMIN_PASSWORD либо
локальные admin credentials из .env. Смена env не меняет пароль существующего
Grafana-пользователя: используйте управление пользователями Grafana.
Prometheus и exporter доступны только внутри Compose. Monitoring не обязателен
для API/worker и не влияет на их readiness. Данные Grafana/Prometheus — в named volumes.

Проверка: загрузите PDF через Documents и нажмите «Обновить» для состояния очереди.
Готовый текст открывается через «Просмотреть текст». Для старого PDF или failed job
кнопка «Переиндексировать» создаёт/повторяет задание. Внешний API:

```sh
curl -i -X POST http://localhost:8000/documents/DOCUMENT_UUID/process \
  -H 'Authorization: Bearer YOUR_JWT'
curl -fsS http://localhost:8000/documents/DOCUMENT_UUID/processing \
  -H 'Authorization: Bearer YOUR_JWT'
docker compose logs --tail=50 worker
docker compose --profile monitoring ps
```

Состояния: queued → processing → succeeded; transient error → retry_wait → processing;
после трёх попыток или постоянной ошибки — failed (сохраняемая dead-letter область).
При падении worker lease истекает через 10 минут, затем работа может продолжиться.
Успешный upload не зависит от доступности Redis в момент commit: задания остаются в БД.
Производительность не измерялась; один tick забирает одно задание раз в пять секунд.
Не масштабируйте worker с embedded beat. Старый синхронный /extract оставлен для
диагностики и обходит очередь; для последовательного теста используйте /process.

Grafana показывает актуальные статусы, heartbeat, возраст ожидания, среднее время
финальной попытки и сообщения Redis. Нет фиктивных метрик или пользовательских
данных в labels. Подробности и ограничения: [ADR 0011](docs/adr/0011-processing-queue-monitoring.md).

Реальный smoke-тест очереди (synthetic PDF, автоматическая очистка своих объектов
и записей; требует запущенных API/worker и monitoring):

```sh
docker compose --profile tools run --rm --no-deps \
  -v "$PWD/scripts:/app/scripts:ro" checks \
  uv run --frozen python scripts/smoke_processing_queue.py
```

Он проверяет два успешных PDF без пересечения времени обработки, permanent failure
повреждённого PDF, чтение извлечённого текста, heartbeat, scrape Prometheus и
авторизованный Grafana dashboard. Для отдельных Grafana credentials передайте
`-e GRAFANA_ADMIN_USER -e GRAFANA_ADMIN_PASSWORD` из окружения оболочки.

## Чанкинг и эмбеддинги

Очередь PDF теперь выполняет весь ingestion до векторного индекса: извлечение →
чанкинг → локальные эмбеддинги → PostgreSQL/Qdrant. Worker остаётся один.
Настройки в `.env` (defaults также передаются Compose):

```dotenv
EMBEDDING_MODEL=embeddinggemma:latest
EMBEDDING_DIMENSIONS=768
CHUNK_SIZE=1000
CHUNK_OVERLAP=150
EMBEDDING_BATCH_SIZE=8
MAX_DOCUMENT_CHUNKS=2000
```

Окна задаются в Unicode-символах, не токенах, отдельно по страницам.
Для этой конфигурации требуется локальная Ollama с установленной embeddinggemma:

```sh
# Выполняется на хосте с существующей установкой Ollama, если модели ещё нет:
ollama pull embeddinggemma:latest
docker compose build api
make migrate
docker compose --profile monitoring up -d --build api worker web-admin queue-metrics prometheus grafana
```

API /index показывает status, chunk_count, embedding_model/digest и dimensions.
После смены параметров или для старого PDF нажмите «Переиндексировать» в Documents
либо вызовите POST /documents/DOCUMENT_UUID/reindex с JWT. Новые PDF индексируются
автоматически. Обычный /process не перестраивает уже успешную задачу.
Несовпадение размерности не усекается автоматически и завершает обработку ошибкой.

SQL хранит текст и метаданные чанков, Qdrant — векторы и ACL-метаданные.
Модельный digest разделяет коллекции, обновление индекса не даёт дублей.
Grafana дополнена indexed documents/chunks; это фактические текущие gauges.
Индексирование ещё не означает наличие API ответов: поиск и генерация подключены отдельно через RAG Playground. Качество и производительность модели не оценивались.
CPU/RAM зависят от локальной модели; текущий ориентир проекта — 16 GB RAM и 20 GB
диска, это не измеренный минимум для любых документов. Учитывайте дополнительные
объёмы текста, векторов и Prometheus. Большие документы ограничены 480 секундами
на попытку и MAX_DOCUMENT_CHUNKS; при ошибке уменьшите ввод/параметры и повторите.

Подробности и ограничения: [ADR 0012](docs/adr/0012-chunking-embeddings.md).

## Поиск и генерация ответов

Откройте **http://localhost:3000/rag**: выберите семью, вопрос и режим keyword/vector/hybrid.
«Только поиск» показывает разрешённые фрагменты без chat-вызова; «Получить ответ»
добавляет локальную генерацию с проверяемыми цитатами, scores, timings и trace ID.
Вход member разрешает RAG-чтение своих доступных документов; сервер проверяет ACL.

```sh
# Локальные модели устанавливаются явно, если ещё отсутствуют:
ollama pull embeddinggemma:latest
ollama pull qwen3:4b
docker compose build api
docker compose up -d --build api web-admin
```

Новых миграций/зависимостей для RAG-чтения нет. Новые API — POST /rag/ask и
POST /rag/search. В .env RAG_MIN_VECTOR_SCORE=0.35 задаёт исходный cosine threshold,
который ещё не калиброван на golden dataset. Keyword/vector — отдельные baselines; hybrid объединяет их через RRF.
При неиндексированном/несовместимом документе выполните reindex в Documents.

Модель получает только разрешённые выдержки; неподтверждённый или некорректно
цитированный ответ заменяется отказом. Сверяйте содержание с источниками: корректные
номера ссылок не гарантируют faithfulness. Retrieval/answer quality пока не измерялись.
Запросы и документы не записываются в telemetry. Streaming и LangGraph — следующие
срезы после базовой оценки.

[API и примеры](docs/api/rag.md), [Advanced RAG: архитектура и ограничения](docs/architecture/advanced-rag.md).
Расширенный scripts/smoke_processing_queue.py теперь также проверяет три retrieval
режима, реальный локальный chat, цитаты и deterministic no-evidence abstention;
нужны API, Web Admin, worker, Ollama, Qdrant и monitoring. Обычные pytest работают с fake LLM.


Upload access includes `member`: any authenticated user may upload to an accessible
family and process/reindex their own document. Family/user management permissions
and private/cross-family isolation are unchanged. See [ADR 0014](docs/adr/0014-member-document-upload.md).

Повторная загрузка одинаковых байтов одним пользователем запрещена (HTTP 409),
даже с другим именем, семьёй или новым ключом. Повтор запроса с прежним ключом
сохраняет идемпотентность; другой пользователь может загрузить тот же файл.
После обновления примените миграцию 0010 через `make migrate`.
[Правила дедупликации](docs/adr/0015-document-content-deduplication.md).

Web Admin поддерживает множественный выбор и пакетную загрузку документов.
Общий размер пакета может превышать 10 MiB, лимит каждого файла — 10 MiB.
Файлы передаются последовательно с индивидуальными результатами и повтором только
неуспешных загрузок. [Описание и smoke-проверка](docs/api/document-upload.md#несколько-файлов-и-пакет-больше-10-mib).

В `/rag` источники сгруппированы по документам, фрагменты и технические сведения
раскрываются по нажатию. Оригинал можно скачать из карточки источника; API повторно
проверяет JWT, семейный доступ и видимость документа.
[Решение и проверки](docs/adr/0017-rag-results-download.md).

Метаданные документов включают `title` из первой содержательной строки расшифровки.
После обновления примените миграцию 0011 (`make migrate`). Старые записи заполнят
заголовок при просмотре текста или переиндексации; до этого UI использует имя файла.
[Правила извлечения](docs/adr/0018-transcript-document-title.md).

## Web Admin: доменные модули и lint

Frontend разделён на `modules/documents`, `identity`, `families`, `rag`, `operations`.
Правила документов — в domain, пакетная загрузка с портами — в application,
HTTP/browser adapters — в infrastructure, Vue/Pinia — в presentation.
ESLint проверяет TypeScript/Vue и границы импортов. Подробнее:
[ADR 0019](docs/adr/0019-web-admin-ddd-lint.md).

`npm run build` обязательно выполняет lint через `prebuild`, затем `vue-tsc` и Vite;
это действует в Docker и CI. Отдельные проверки без host Node:

```sh
docker compose --profile tools run --build --rm --no-deps web-checks npm run lint
docker compose --profile tools run --rm --no-deps web-checks npm test
```

Для локального редактирования есть `npm run lint:fix`; сборка сама файлы не исправляет.

Проверка известных уязвимостей Web Admin (включая devDependencies) выполняется
отдельно от build и требует доступа к npm registry:

```sh
docker compose --profile tools run --build --rm --no-deps web-checks npm run audit
```

CI запускает этот audit после основных проверок и отклоняет найденные уязвимости
начиная с low. Версии и обоснование обновления:
[ADR 0020](docs/adr/0020-web-dependency-security-update.md).

RAG latency/throughput: Grafana http://localhost:3001/d/rag-performance (папка RAG).
Показаны p50/p95 поиска и этапов, частота запросов, ошибки, abstention и ожидание
слота. Prometheus собирает агрегаты с API `/internal/metrics`; SPA proxy закрывает
этот endpoint. Настройки monitoring и значения histogram требуют реальных запросов
и нескольких scrapes. [Семантика метрик](docs/adr/0021-rag-stage-prometheus-metrics.md).

Query Rewriting for empty `/rag/ask` retrieval is enabled by
`RAG_QUERY_REWRITING=true`; set it to `false` for the baseline. One rewrite attempt
(maximum 10 seconds) retries the same retrieval mode with fresh ACL scopes.
Answers use the original question; `/rag/search` stays model-free.
See [ADR 0022](docs/adr/0022-query-rewriting.md) for limits and telemetry.

Advanced RAG: choose Hybrid in the Playground (UI default), or send
`retrieval_mode: "hybrid"` to `/rag/ask` or `/rag/search`. API default remains vector.
FTS/vector baselines remain selectable. Hybrid uses RRF (k=60); `/rag/ask` may
rerank authorized candidates with the configured Ollama chat model. Set
`RAG_RERANKING=false` to compare RRF alone. `/rag/search` never invokes the chat
model. This is an LLM reranker, not a cross-encoder; quality gains are not measured.
See [ADR 0023](docs/adr/0023-advanced-rag.md) for ACL, scoring and failure behavior.
