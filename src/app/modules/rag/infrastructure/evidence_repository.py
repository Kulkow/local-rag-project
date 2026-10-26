"""Short PostgreSQL reads with repeated live user/family/document/index authorization."""

import re
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSQUERY, TSVECTOR
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.documents.infrastructure.chunk_repository import chunks_table, indexes
from app.modules.documents.infrastructure.repository import documents
from app.modules.documents.infrastructure.family_access import ScopedFamilyAccess
from app.modules.families.infrastructure.persistence import family_members
from app.modules.identity.application.contracts import Principal
from app.modules.identity.infrastructure.repository import users, SqlIdentityRepository
from app.modules.rag.application.answering import Candidate, RetrievedChunk, Scope
from app.modules.shared.domain.errors import ApplicationError


class SqlEvidenceRepository:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory
        self.access = ScopedFamilyAccess(factory)

    @staticmethod
    def scope(actor: Principal, family_id: UUID) -> sa.ColumnElement[bool]:
        active = sa.exists(
            sa.select(users.c.id).where(
                users.c.id == actor.id,
                users.c.token_version == actor.token_version,
                users.c.is_active,
            )
        )
        membership = (
            sa.true()
            if actor.is_admin
            else sa.exists(
                sa.select(family_members.c.id).where(
                    family_members.c.id == actor.family_member_id,
                    family_members.c.family_id == family_id,
                )
            )
        )
        visibility = (
            sa.true()
            if actor.is_admin
            else sa.or_(documents.c.owner_id == actor.id, documents.c.visibility == "family")
        )
        return sa.and_(
            active,
            membership,
            visibility,
            documents.c.family_id == family_id,
            documents.c.status == "uploaded",
            indexes.c.status == "indexed",
            indexes.c.source_checksum == documents.c.checksum,
        )

    async def scopes(self, actor: Principal, family_id: UUID) -> list[Scope]:
        await self.access.authorize(actor, family_id)
        async with self.factory() as session:
            rows = (
                await session.execute(
                    sa.select(
                        indexes.c.document_id,
                        indexes.c.generation,
                        indexes.c.collection_name,
                        indexes.c.embedding_model,
                        indexes.c.embedding_digest,
                        indexes.c.dimensions,
                    )
                    .join(documents, documents.c.id == indexes.c.document_id)
                    .where(self.scope(actor, family_id))
                    .order_by(indexes.c.document_id)
                    .limit(501)
                )
            ).all()
        if len(rows) > 500:
            raise ApplicationError(
                "throttled", "Too many indexed documents in this scope; narrow the knowledge base"
            )
        return [Scope(*row) for row in rows]

    @staticmethod
    def selection(
        actor: Principal, family_id: UUID
    ) -> sa.Select[tuple[UUID, UUID, UUID, str, int, str]]:
        return (
            sa.select(
                chunks_table.c.id,
                chunks_table.c.document_id,
                chunks_table.c.index_generation,
                documents.c.filename,
                chunks_table.c.page_number,
                chunks_table.c.text,
            )
            .select_from(
                chunks_table.join(documents, documents.c.id == chunks_table.c.document_id).join(
                    indexes, indexes.c.document_id == documents.c.id
                )
            )
            .where(
                SqlEvidenceRepository.scope(actor, family_id),
                chunks_table.c.index_generation == indexes.c.generation,
            )
        )

    async def keyword(
        self, actor: Principal, family_id: UUID, question: str, top_k: int
    ) -> list[RetrievedChunk]:
        search_vector = sa.literal_column("document_chunks.search_vector", type_=TSVECTOR())
        query = sa.func.plainto_tsquery("simple", question)
        russian_vector = sa.literal_column("document_chunks.search_vector_ru", type_=TSVECTOR())
        russian_query: sa.ColumnElement[str] = sa.func.plainto_tsquery("russian", question)
        # Snowball over-stems singular "лейкоцит" to "лейкоц", while the plural
        # becomes "лейкоцит". A bounded single-word prefix bridges these stems.
        # Build syntax from PostgreSQL's escaped tsquery, never raw user input.
        if re.fullmatch(r"[А-Яа-яЁё]{4,}", question.strip()):
            russian_query = sa.case(
                (
                    sa.func.numnode(russian_query) > 0,
                    sa.cast(sa.cast(russian_query, sa.Text).concat(":*"), TSQUERY()),
                ),
                else_=russian_query,
            )
        score = sa.func.greatest(
            sa.func.ts_rank_cd(search_vector, query),
            sa.func.ts_rank_cd(russian_vector, russian_query),
        ).label("score")
        async with self.factory() as session:
            await session.execute(sa.text("SET statement_timeout = '5000ms'"))
            rows = (
                await session.execute(
                    self.selection(actor, family_id)
                    .add_columns(score)
                    .where(
                        sa.or_(
                            search_vector.op("@@")(query),
                            russian_vector.op("@@")(russian_query),
                        )
                    )
                    .order_by(score.desc(), chunks_table.c.id)
                    .limit(top_k)
                )
            ).all()
        return [RetrievedChunk(*row) for row in rows]

    async def read_candidates(
        self, actor: Principal, family_id: UUID, candidates: list[Candidate], top_k: int
    ) -> list[RetrievedChunk]:
        if not candidates:
            return []
        candidates_by_id = {candidate.chunk_id: candidate for candidate in candidates}
        async with self.factory() as session:
            rows = (
                await session.execute(
                    self.selection(actor, family_id).where(chunks_table.c.id.in_(candidates_by_id))
                )
            ).all()
        result: list[RetrievedChunk] = []
        for row in rows:
            candidate = candidates_by_id[row.id]
            if (
                candidate.document_id == row.document_id
                and candidate.generation == row.index_generation
            ):
                result.append(
                    RetrievedChunk(
                        row.id,
                        row.document_id,
                        row.index_generation,
                        row.filename,
                        row.page_number,
                        row.text,
                        candidate.score,
                    )
                )
        return sorted(result, key=lambda item: (-item.score, str(item.chunk_id)))[:top_k]

    async def revalidate(
        self, actor: Principal, family_id: UUID, chunks: list[RetrievedChunk]
    ) -> None:
        async with self.factory() as session:
            current = await SqlIdentityRepository(session).principal(actor.id, actor.token_version)
            if current is None:
                raise ApplicationError("unauthorized", "Authentication was revoked")
        await self.access.authorize(current, family_id)
        candidates = [
            Candidate(chunk.chunk_id, chunk.document_id, chunk.generation, chunk.score)
            for chunk in chunks
        ]
        visible = await self.read_candidates(current, family_id, candidates, len(chunks))
        if {chunk.chunk_id for chunk in visible} != {chunk.chunk_id for chunk in chunks}:
            raise ApplicationError("conflict", "Evidence changed during the request; retry")
