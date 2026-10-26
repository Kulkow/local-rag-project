import os
from dataclasses import replace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.documents.application.indexing import IndexRecord
from app.modules.documents.domain.chunking import ChunkingConfig, chunk_pages
from app.modules.documents.domain.extraction import PageText
from app.modules.documents.infrastructure.chunk_repository import SqlChunkIndex, chunks_table
from app.modules.shared.domain.errors import ApplicationError


async def test_chunk_catalog_atomic_replacement_search_and_stale_generation() -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to migrated PostgreSQL")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection, connection.begin():
            schema = "chunk_test_" + uuid4().hex
            await connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
            for table in ("document_indexes", "document_chunks"):
                await connection.execute(
                    sa.text(f"CREATE TABLE {table} (LIKE public.{table} INCLUDING ALL)")
                )
            factory = async_sessionmaker(
                connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )
            repository = SqlChunkIndex(factory)
            document_id = uuid4()
            config = ChunkingConfig(100, 10)
            chunks = chunk_pages(
                document_id, "a" * 64, (PageText(1, "Synthetic searchable evidence"),), config
            )
            record = IndexRecord(
                document_id, uuid4(), "a" * 64, "indexing", "synthetic", "fake", "fake-digest", 3
            )
            await repository.start(record, uuid4(), "a" * 64, config)
            await repository.complete(record, chunks)
            stored = await repository.get(document_id)
            assert stored and stored.status == "indexed" and stored.chunk_count == 1
            assert (
                await connection.scalar(
                    sa.text(
                        "SELECT count(*) FROM document_chunks WHERE search_vector @@ plainto_tsquery('simple', 'evidence')"
                    )
                )
                == 1
            )
            newer = replace(record, generation=uuid4(), fingerprint="b" * 64)
            await repository.start(newer, uuid4(), "a" * 64, config)
            with pytest.raises(ApplicationError):
                await repository.complete(record, chunks)
            await repository.fail(record)
            assert (await repository.get(document_id)).status == "indexing"
            await repository.complete(newer, chunks)
            assert (
                await connection.scalar(sa.select(sa.func.count()).select_from(chunks_table)) == 1
            )
            assert (
                await connection.scalar(sa.select(chunks_table.c.index_generation))
                == newer.generation
            )
            await connection.rollback()
    finally:
        await engine.dispose()
