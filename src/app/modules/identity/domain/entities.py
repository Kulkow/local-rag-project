from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


class UserRole(StrEnum):
    ADMIN = "admin"
    MANAGER = "manager"
    MEMBER = "member"


@dataclass(frozen=True)
class Principal:
    id: UUID
    username: str
    role: UserRole
    family_member_id: UUID | None
    is_active: bool = True
    token_version: int = 0

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN


@dataclass(frozen=True)
class User:
    principal: Principal
    password_hash: str = field(repr=False)
