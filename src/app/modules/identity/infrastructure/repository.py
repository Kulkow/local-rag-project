from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.domain.entities import Principal, User, UserRole
from app.modules.shared.domain.errors import ApplicationError

metadata = sa.MetaData()
users = sa.Table(
    "users",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("username", sa.String(100)),
    sa.Column("password_hash", sa.String(255)),
    sa.Column("role", sa.String(20)),
    sa.Column("is_active", sa.Boolean()),
    sa.Column("family_member_id", sa.Uuid()),
    sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
)


def principal(row: sa.RowMapping) -> Principal:
    return Principal(
        row["id"],
        row["username"],
        UserRole(row["role"]),
        row["family_member_id"],
        row["is_active"],
        row["token_version"],
    )


class SqlIdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_username(self, username: str) -> User | None:
        row = (
            (await self.session.execute(sa.select(users).where(users.c.username == username)))
            .mappings()
            .first()
        )
        return User(principal(row), row["password_hash"]) if row else None

    async def save_user(self, user: User) -> None:
        actor = user.principal
        await self.session.execute(
            sa.insert(users).values(
                id=actor.id,
                username=actor.username,
                password_hash=user.password_hash,
                role=actor.role.value,
                is_active=actor.is_active,
                family_member_id=actor.family_member_id,
            )
        )

    async def users(self, offset: int, limit: int) -> list[Principal]:
        rows = (
            await self.session.execute(
                sa.select(users).order_by(users.c.username).offset(offset).limit(limit)
            )
        ).mappings()
        return [principal(row) for row in rows]

    async def update_user(
        self,
        user_id: UUID,
        role: UserRole,
        active: bool,
        member_id: UUID | None,
        password_hash: str | None,
    ) -> Principal:
        # Serializes admin demotions, preventing concurrent removal of the last active admin.
        await self.session.execute(sa.text("SELECT pg_advisory_xact_lock(739102)"))
        old = (
            (
                await self.session.execute(
                    sa.select(users).where(users.c.id == user_id).with_for_update()
                )
            )
            .mappings()
            .first()
        )
        if old is None:
            raise ApplicationError("not_found", "User not found")
        if old["role"] == "admin" and old["is_active"] and (role != UserRole.ADMIN or not active):
            count = (
                await self.session.execute(
                    sa.select(sa.func.count())
                    .select_from(users)
                    .where(users.c.role == "admin", users.c.is_active)
                )
            ).scalar_one()
            if count <= 1:
                raise ApplicationError(
                    "conflict", "Cannot disable or demote the last administrator"
                )
        values: dict[str, object] = dict(
            role=role.value,
            is_active=active,
            family_member_id=member_id,
            token_version=users.c.token_version + 1,
        )
        if password_hash:
            values["password_hash"] = password_hash
        row = (
            (
                await self.session.execute(
                    sa.update(users).where(users.c.id == user_id).values(**values).returning(users)
                )
            )
            .mappings()
            .one()
        )
        return principal(row)

    async def principal(self, user_id: UUID, token_version: int) -> Principal | None:
        row = (
            (
                await self.session.execute(
                    sa.select(users).where(
                        users.c.id == user_id,
                        users.c.token_version == token_version,
                        users.c.is_active,
                    )
                )
            )
            .mappings()
            .first()
        )
        return principal(row) if row else None

    async def active_principal(self, user_id: UUID) -> Principal | None:
        """Reload current permissions for a durable background job; no JWT is stored."""
        row = (
            (
                await self.session.execute(
                    sa.select(users).where(users.c.id == user_id, users.c.is_active)
                )
            )
            .mappings()
            .first()
        )
        return principal(row) if row else None

    async def revoke(self, user_id: UUID, token_version: int) -> None:
        await self.session.execute(
            sa.update(users)
            .where(users.c.id == user_id, users.c.token_version == token_version)
            .values(token_version=users.c.token_version + 1)
        )

    async def allow_login(self, key: str) -> bool:
        # A separate short transaction commits failed attempts too; shared by API processes.
        engine = self.session.bind
        assert engine is not None
        async with AsyncSession(bind=engine) as transaction:
            attempts = (
                await transaction.execute(
                    sa.text("""
                INSERT INTO login_attempts (key, window_start, attempts) VALUES (:key, now(), 1)
                ON CONFLICT (key) DO UPDATE SET
                attempts = CASE WHEN login_attempts.window_start < now() - interval '1 minute' THEN 1 ELSE login_attempts.attempts + 1 END,
                window_start = CASE WHEN login_attempts.window_start < now() - interval '1 minute' THEN now() ELSE login_attempts.window_start END
                RETURNING attempts
            """),
                    {"key": key},
                )
            ).scalar_one()
            await transaction.execute(
                sa.text("DELETE FROM login_attempts WHERE window_start < now() - interval '1 day'")
            )
            await transaction.commit()
        return bool(attempts <= 10)
