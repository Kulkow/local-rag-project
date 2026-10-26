"""Real PostgreSQL queue transitions in a rollback-only isolated schema."""

import os
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.documents.domain.processing import ProcessingStatus
from app.modules.documents.infrastructure.processing_repository import SqlProcessingRepository, jobs


async def test_durable_queue_retry_recovery_and_generation_fencing() -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to migrated PostgreSQL")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection, connection.begin():
            schema = "queue_test_" + uuid4().hex
            await connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
            # LIKE copies real defaults/checks/indexes, without the unrelated users/documents FKs.
            await connection.execute(
                sa.text(
                    "CREATE TABLE document_processing_jobs (LIKE public.document_processing_jobs INCLUDING ALL)"
                )
            )
            factory = async_sessionmaker(
                connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )
            repository = SqlProcessingRepository(factory)
            document_id, actor_id = uuid4(), uuid4()
            first = await repository.enqueue(document_id, actor_id)
            assert first.status == ProcessingStatus.QUEUED and first.attempts == 0
            assert (await repository.enqueue(document_id, actor_id)).generation == first.generation
            run = await repository.claim()
            assert run and run.attempts == 1
            assert await repository.claim() is None
            await repository.fail(run, "storage_unavailable", True)
            assert (await repository.get(document_id)).status == ProcessingStatus.RETRY_WAIT
            assert await repository.claim() is None
            await connection.execute(
                sa.update(jobs).values(available_at=sa.func.now() - sa.text("interval '1 minute'"))
            )
            second = await repository.claim()
            assert second and second.attempts == 2 and second.generation != run.generation
            await repository.succeed(run)
            assert (await repository.get(document_id)).status == ProcessingStatus.PROCESSING
            await repository.succeed(second)
            assert (await repository.get(document_id)).status == ProcessingStatus.SUCCEEDED
            await repository.fail(second, "processing_unavailable", False)
            assert (await repository.get(document_id)).status == ProcessingStatus.SUCCEEDED
            rebuilt = await repository.enqueue(document_id, actor_id, force=True)
            assert rebuilt.status == ProcessingStatus.QUEUED and rebuilt.reindex
            # Simulate a crashed worker on its last attempt: recovery records a terminal failure.
            await connection.execute(
                sa.update(jobs).values(
                    status="processing",
                    attempts=3,
                    lease_until=sa.func.now() - sa.text("interval '1 minute'"),
                )
            )
            assert await repository.claim() is None
            failed = await repository.get(document_id)
            assert failed.status == ProcessingStatus.FAILED and failed.error_code == "worker_lost"
            restarted = await repository.enqueue(document_id, actor_id)
            assert restarted.attempts == 0 and restarted.status == ProcessingStatus.QUEUED
            # Roll back the schema as well as test rows.
            await connection.rollback()
    finally:
        await engine.dispose()
