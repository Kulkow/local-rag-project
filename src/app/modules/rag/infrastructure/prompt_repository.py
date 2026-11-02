"""One deployment-wide prompt, with atomic version checks for concurrent editors."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.rag.application.prompt_settings import PromptSettings
from app.modules.shared.domain.errors import ApplicationError

metadata = sa.MetaData()
prompt_settings = sa.Table(
    "rag_prompt_settings",
    metadata,
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("system_prompt", sa.Text(), nullable=False),
    sa.Column("version", sa.Integer(), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)


def settings_from_row(row: sa.RowMapping) -> PromptSettings:
    return PromptSettings(row["system_prompt"], row["version"], row["updated_at"])


class SqlPromptStore:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory

    async def get(self) -> PromptSettings:
        async with self.factory() as session:
            row = (
                (await session.execute(sa.select(prompt_settings).where(prompt_settings.c.id == 1)))
                .mappings()
                .first()
            )
            return settings_from_row(row) if row else PromptSettings()

    async def save(self, system_prompt: str, expected_version: int) -> PromptSettings:
        async with self.factory() as session, session.begin():
            if expected_version == 0:
                statement = (
                    insert(prompt_settings)
                    .values(id=1, system_prompt=system_prompt, version=1, updated_at=sa.func.now())
                    .on_conflict_do_nothing(index_elements=["id"])
                    .returning(prompt_settings)
                )
                row = (await session.execute(statement)).mappings().first()
            else:
                row = (
                    (
                        await session.execute(
                            sa.update(prompt_settings)
                            .where(
                                prompt_settings.c.id == 1,
                                prompt_settings.c.version == expected_version,
                            )
                            .values(
                                system_prompt=system_prompt,
                                version=expected_version + 1,
                                updated_at=sa.func.now(),
                            )
                            .returning(prompt_settings)
                        )
                    )
                    .mappings()
                    .first()
                )
            if row is None:
                raise ApplicationError("conflict", "Settings changed; reload before saving")
            return settings_from_row(row)
