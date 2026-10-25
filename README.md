# Enterprise RAG Platform

Docker-first reference project, Phase 1: FastAPI, async PostgreSQL, Alembic,
Celery/Redis, Qdrant, MinIO, host-installed Ollama and Vue 3/Vite/PrimeVue 4/Pinia administration.
Document ingestion, RAG and agent workflows are future phases, not implemented features.

## Start

Docker Engine with Compose v2 and a running host-installed Ollama are required.
The root configuration is `docker-compose.yaml`; `docker compose` finds it automatically.
CPU operation is the default.
Plan for 16 GB RAM (at least 10 GB allocated to Docker) and 20 GB free disk.
Initial builds and model downloads require internet access.

```sh
cp -n .env.example .env
# Edit .env: set POSTGRES_PASSWORD, MINIO_ROOT_USER, MINIO_ROOT_PASSWORD,
# ADMIN_USERNAME and ADMIN_PASSWORD to your own nonempty values.
# Use URL-safe random PostgreSQL passwords; MinIO password must be >=8 characters.
make lock
docker compose config --quiet
docker compose up -d --build
docker compose ps
make smoke
```

Web Admin: http://localhost:3000 — enter ADMIN_USERNAME and ADMIN_PASSWORD to check
live services. API/OpenAPI: http://localhost:8000/docs. MinIO: http://localhost:9001.
Browser API calls use Nginx `/api`; no cross-origin CORS access is enabled.
Container ports bind only to localhost. Databases and object API are internal.
Ollama runs on the host; containers use `host.docker.internal:11434`.
No default administrator credentials are supplied. `.env` is ignored by Git.

Migrations run once through the `migrate` service before API/worker startup.
For later schema updates run `make migrate`. Do not delete named volumes to upgrade.
`docker compose down` preserves data. Administrator credentials can be rotated by
editing `.env` then recreating API and worker (`docker compose up -d --force-recreate
api worker`); existing in-memory browser credentials must be entered again.
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
docker compose --profile tools run --rm -v "$PWD/web-admin:/app/web-admin" checks python scripts/export_openapi.py
docker compose --profile tools run --rm -v "$PWD/web-admin:/contract" web-checks npx openapi-typescript /contract/openapi.json -o /contract/src/schema.ts
```

## Models

The local model store contains `qwen3:4b` and `embeddinggemma:latest`.
These are selected in `.env` and `.env.example`. Availability was confirmed from
local manifest files; inference has not been tested.

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
phases and does not yet trigger inference. Embedding dimensions will be validated
when ingestion is implemented.

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

`src/app/api`: HTTP DTOs and probes; `core`: typed settings;
`infrastructure/db`: async engine; `infrastructure/queue`: bounded Celery worker;
`migrations`: schema; `web-admin`: typed SPA; `tests`: unit and DB integration.
See [ADR 0001](docs/adr/0001-foundation.md).

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
