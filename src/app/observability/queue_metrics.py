"""Private Prometheus endpoint. Only aggregate operational metadata is exposed."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import sqlalchemy as sa
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from redis.asyncio import Redis

from app.core.settings import Settings
from app.infrastructure.db.connection import create_engine
from app.modules.documents.domain.processing import ProcessingStatus
from app.modules.documents.infrastructure.processing_repository import jobs
from app.modules.documents.infrastructure.chunk_repository import indexes
from app.modules.documents.infrastructure.processing_worker import HEARTBEAT_KEY


def render_queue_metrics(
    counts: dict[str, int],
    oldest: float,
    duration: float,
    heartbeat: bool,
    broker_depth: int,
    indexed_documents: int = 0,
    indexed_chunks: int = 0,
) -> str:
    lines = [
        "# HELP rag_document_jobs Current durable document jobs by status (not attempt counters).",
        "# TYPE rag_document_jobs gauge",
    ]
    for status in ProcessingStatus:
        lines.append(f'rag_document_jobs{{status="{status.value}"}} {counts.get(status.value, 0)}')
    for name, help_text, value in [
        ("rag_indexed_documents", "Current indexed documents in PostgreSQL.", indexed_documents),
        ("rag_indexed_chunks", "Chunks belonging to current indexed documents.", indexed_chunks),
        ("rag_document_queue_oldest_seconds", "Age of oldest waiting document job.", oldest),
        (
            "rag_document_processing_average_seconds",
            "Mean final-attempt runtime of retained terminal jobs.",
            duration,
        ),
        ("rag_document_worker_heartbeat", "Worker tick seen within 600 seconds.", int(heartbeat)),
        (
            "rag_celery_broker_messages",
            "Redis default Celery list length, including scheduler ticks.",
            broker_depth,
        ),
    ]:
        lines.extend([f"# HELP {name} {help_text}", f"# TYPE {name} gauge", f"{name} {value}"])
    return "\n".join(lines) + "\n"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config = Settings()
    engine = create_engine(config.database_url.get_secret_value())
    app.state.engine = engine
    app.state.redis = Redis.from_url(config.redis_url, socket_timeout=3, socket_connect_timeout=3)
    try:
        yield
    finally:
        await app.state.redis.aclose()
        await engine.dispose()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request) -> PlainTextResponse:
    async with request.app.state.engine.connect() as connection:
        await connection.execute(sa.text("SET statement_timeout = '3000ms'"))
        counts = {
            row[0]: row[1]
            for row in (
                await connection.execute(
                    sa.select(jobs.c.status, sa.func.count()).group_by(jobs.c.status)
                )
            ).all()
        }
        oldest = await connection.scalar(
            sa.select(
                sa.func.coalesce(
                    sa.func.max(sa.extract("epoch", sa.func.now() - jobs.c.created_at)), 0
                )
            ).where(jobs.c.status.in_(["queued", "retry_wait"]))
        )
        duration = await connection.scalar(
            sa.select(
                sa.func.coalesce(
                    sa.func.avg(sa.extract("epoch", jobs.c.finished_at - jobs.c.started_at)), 0
                )
            ).where(jobs.c.status.in_(["succeeded", "failed"]))
        )
        indexed_documents = await connection.scalar(
            sa.select(sa.func.count()).select_from(indexes).where(indexes.c.status == "indexed")
        )
        indexed_chunks = await connection.scalar(
            sa.select(sa.func.coalesce(sa.func.sum(indexes.c.chunk_count), 0)).where(
                indexes.c.status == "indexed"
            )
        )
    redis = request.app.state.redis
    heartbeat = bool(await redis.exists(HEARTBEAT_KEY))
    depth = int(await redis.llen("celery"))
    return PlainTextResponse(
        render_queue_metrics(
            counts,
            float(oldest),
            float(duration),
            heartbeat,
            depth,
            int(indexed_documents),
            int(indexed_chunks),
        ),
        media_type="text/plain; version=0.0.4",
    )
