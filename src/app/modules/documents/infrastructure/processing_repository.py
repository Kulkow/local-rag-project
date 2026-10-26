from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.documents.domain.processing import ProcessingJob, ProcessingStatus
from app.modules.shared.domain.errors import ApplicationError

metadata = sa.MetaData()
jobs = sa.Table(
    "document_processing_jobs",
    metadata,
    sa.Column("document_id", sa.Uuid(), primary_key=True),
    sa.Column("requested_by", sa.Uuid()),
    sa.Column("generation", sa.Uuid()),
    sa.Column("status", sa.String(20)),
    sa.Column("attempts", sa.Integer()),
    sa.Column("reindex_requested", sa.Boolean()),
    sa.Column("error_code", sa.String(50)),
    sa.Column("available_at", sa.DateTime(timezone=True)),
    sa.Column("lease_until", sa.DateTime(timezone=True)),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("started_at", sa.DateTime(timezone=True)),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
)


def to_job(row: sa.RowMapping) -> ProcessingJob:
    return ProcessingJob(
        row["document_id"],
        row["requested_by"],
        row["generation"],
        ProcessingStatus(row["status"]),
        row["attempts"],
        row["error_code"],
        row["created_at"],
        row["started_at"],
        row["finished_at"],
        row["reindex_requested"],
    )


async def schedule_job(session: AsyncSession, document_id: UUID, requested_by: UUID) -> None:
    """Called inside the same transaction that marks the original uploaded."""
    await session.execute(
        insert(jobs)
        .values(
            document_id=document_id, requested_by=requested_by, generation=uuid4(), status="queued"
        )
        .on_conflict_do_nothing(index_elements=[jobs.c.document_id])
    )


class SqlProcessingRepository:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory

    async def get(self, document_id: UUID) -> ProcessingJob:
        async with self.factory() as session:
            row = (
                (await session.execute(sa.select(jobs).where(jobs.c.document_id == document_id)))
                .mappings()
                .first()
            )
            if row is None:
                raise ApplicationError("not_found", "Processing has not been scheduled")
            return to_job(row)

    async def enqueue(
        self, document_id: UUID, requested_by: UUID, force: bool = False
    ) -> ProcessingJob:
        async with self.factory() as session, session.begin():
            await schedule_job(session, document_id, requested_by)
            # Only terminal failure is explicitly restartable. Active/successful work is idempotent.
            await session.execute(
                sa.update(jobs)
                .where(
                    jobs.c.document_id == document_id,
                    jobs.c.status.in_(["failed", "succeeded"] if force else ["failed"]),
                )
                .values(
                    requested_by=requested_by,
                    generation=uuid4(),
                    status="queued",
                    attempts=0,
                    reindex_requested=force,
                    error_code=None,
                    available_at=sa.func.now(),
                    lease_until=None,
                    started_at=None,
                    finished_at=None,
                )
            )
        return await self.get(document_id)

    async def claim(self) -> ProcessingJob | None:
        async with self.factory() as session, session.begin():
            expired = sa.and_(jobs.c.status == "processing", jobs.c.lease_until < sa.func.now())
            await session.execute(
                sa.update(jobs)
                .where(expired, jobs.c.attempts >= 3)
                .values(
                    status="failed",
                    error_code="worker_lost",
                    finished_at=sa.func.now(),
                    lease_until=None,
                )
            )
            row = (
                (
                    await session.execute(
                        sa.select(jobs)
                        .where(
                            sa.or_(
                                sa.and_(
                                    jobs.c.status.in_(["queued", "retry_wait"]),
                                    jobs.c.available_at <= sa.func.now(),
                                ),
                                expired,
                            ),
                            jobs.c.attempts < 3,
                        )
                        .order_by(jobs.c.available_at, jobs.c.document_id)
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            result = (
                (
                    await session.execute(
                        sa.update(jobs)
                        .where(jobs.c.document_id == row["document_id"])
                        .values(
                            generation=uuid4(),
                            status="processing",
                            attempts=jobs.c.attempts + 1,
                            error_code=None,
                            started_at=sa.func.now(),
                            finished_at=None,
                            lease_until=sa.func.now() + sa.text("interval '10 minutes'"),
                        )
                        .returning(jobs)
                    )
                )
                .mappings()
                .one()
            )
            return to_job(result)

    async def succeed(self, job: ProcessingJob) -> None:
        await self._finish(job, "succeeded", None, 0)

    async def fail(self, job: ProcessingJob, code: str, retry: bool) -> None:
        # The extraction lease lasts five minutes. A conflicting attempt must wait it out.
        delay = 310 if code == "conflict" else 10 * 2 ** (job.attempts - 1)
        await self._finish(job, "retry_wait" if retry else "failed", code, delay)

    async def _finish(self, job: ProcessingJob, status: str, code: str | None, delay: int) -> None:
        async with self.factory() as session, session.begin():
            await session.execute(
                sa.update(jobs)
                .where(
                    jobs.c.document_id == job.document_id,
                    jobs.c.generation == job.generation,
                    jobs.c.status == "processing",
                )
                .values(
                    status=status,
                    error_code=code,
                    lease_until=None,
                    finished_at=None if status == "retry_wait" else sa.func.now(),
                    available_at=sa.func.now() + sa.func.make_interval(0, 0, 0, 0, 0, 0, delay),
                )
            )
