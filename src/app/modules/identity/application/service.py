from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from app.modules.identity.domain.entities import Principal, User, UserRole
from app.modules.shared.domain.errors import ApplicationError


class IdentityRepository(Protocol):
    async def by_username(self, username: str) -> User | None: ...
    async def save_user(self, user: User) -> None: ...
    async def users(self, offset: int, limit: int) -> list[Principal]: ...
    async def update_user(
        self,
        user_id: UUID,
        role: UserRole,
        active: bool,
        member_id: UUID | None,
        password_hash: str | None,
    ) -> Principal: ...
    async def principal(self, user_id: UUID, token_version: int) -> Principal | None: ...
    async def revoke(self, user_id: UUID, token_version: int) -> None: ...
    async def allow_login(self, key: str) -> bool: ...


class Passwords(Protocol):
    async def hash(self, password: str) -> str: ...
    async def verify(self, password: str, encoded: str | None) -> bool: ...


@dataclass(frozen=True)
class TokenClaims:
    user_id: UUID
    version: int


class Tokens(Protocol):
    def issue(self, actor: Principal) -> str: ...
    def decode(self, token: str) -> TokenClaims: ...
    def digest(self, token: str) -> str: ...


class IdentityService:
    def __init__(
        self, repository: IdentityRepository, passwords: Passwords, tokens: Tokens
    ) -> None:
        self.repository = repository
        self.passwords = passwords
        self.tokens = tokens

    @staticmethod
    def require_admin(actor: Principal) -> None:
        if not actor.is_admin:
            raise ApplicationError("forbidden", "Administrator access required")

    @staticmethod
    def validate_link(role: UserRole, member_id: UUID | None) -> None:
        if role != UserRole.ADMIN and member_id is None:
            raise ApplicationError(
                "invalid", "A manager or member must be linked to a family member"
            )

    async def login(self, username: str, password: str, client: str) -> tuple[str, Principal]:
        username = username.strip().lower()
        if not await self.repository.allow_login(self.tokens.digest(client)):
            raise ApplicationError("throttled", "Too many login attempts; retry in one minute")
        user = await self.repository.by_username(username)
        valid = await self.passwords.verify(password, user.password_hash if user else None)
        if not user or not valid or not user.principal.is_active:
            raise ApplicationError("unauthorized", "Invalid credentials")
        token = self.tokens.issue(user.principal)
        return token, user.principal

    async def authenticate(self, token: str) -> Principal:
        claims = self.tokens.decode(token)
        actor = await self.repository.principal(claims.user_id, claims.version)
        if actor is None:
            raise ApplicationError("unauthorized", "Token expired or revoked")
        return actor

    async def create_user(
        self, actor: Principal, username: str, password: str, role: UserRole, member_id: UUID | None
    ) -> Principal:
        self.require_admin(actor)
        self.validate_link(role, member_id)
        principal = Principal(uuid4(), username.strip().lower(), role, member_id)
        await self.repository.save_user(User(principal, await self.passwords.hash(password)))
        return principal

    async def list_users(self, actor: Principal, offset: int, limit: int) -> list[Principal]:
        self.require_admin(actor)
        return await self.repository.users(offset, limit)

    async def update_user(
        self,
        actor: Principal,
        user_id: UUID,
        role: UserRole,
        active: bool,
        member_id: UUID | None,
        password: str | None,
    ) -> Principal:
        self.require_admin(actor)
        self.validate_link(role, member_id)
        encoded = await self.passwords.hash(password) if password else None
        return await self.repository.update_user(user_id, role, active, member_id, encoded)

    async def logout(self, token: str) -> None:
        claims = self.tokens.decode(token)
        await self.repository.revoke(claims.user_id, claims.version)
