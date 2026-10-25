# ADR 0001: Docker-first foundation

Use a modular FastAPI monolith, async SQLAlchemy and a separately invoked Alembic
migration service. API readiness checks the migration marker and real dependency
endpoints concurrently with bounded timeouts; process liveness is independent.
Qdrant and MinIO readiness is verified by the API because their minimal images
are not assumed to contain curl. The worker has a directed Celery ping check.

Phase 1 uses a single explicit environment-configured administrator and HTTP
Basic authentication over loopback-only local ports. The dashboard keeps credentials
in memory. Remote deployments require TLS; persisted tenant users, roles and secure
sessions belong to later phases. No document endpoints exist yet.

Dependencies: httpx supplies bounded HTTP probes, Redis supplies asynchronous broker
health checks, Celery supplies the worker, SQLAlchemy/asyncpg and Alembic supply
async database access and migrations. Vue Router, Pinia and PrimeVue provide the
required SPA foundation; Vitest tests API failures. openapi-typescript generates
the REST contract from FastAPI. LangGraph/model SDKs are deferred until used.

This is a reference project. No production or benchmark claims are made.
