from uuid import uuid4

import pytest

from app.modules.identity.application.service import IdentityService
from app.modules.identity.domain.entities import Principal, UserRole
from app.modules.identity.infrastructure.security import ScryptPasswords, JwtTokens
from app.modules.shared.domain.errors import ApplicationError


def test_user_permissions_and_member_link() -> None:
    member = Principal(uuid4(), "member", UserRole.MEMBER, uuid4())
    with pytest.raises(ApplicationError):
        IdentityService.require_admin(member)
    for role in (UserRole.MANAGER, UserRole.MEMBER):
        with pytest.raises(ApplicationError):
            IdentityService.validate_link(role, None)
    IdentityService.validate_link(UserRole.ADMIN, None)


async def test_password_hashes_are_salted_and_verified() -> None:
    passwords = ScryptPasswords()
    first = await passwords.hash("synthetic-password-123")
    second = await passwords.hash("synthetic-password-123")
    assert first != second
    assert await passwords.verify("synthetic-password-123", first)
    assert not await passwords.verify("wrong", first)
    assert not await passwords.verify("synthetic-password-123", None)
    assert not await passwords.verify("wrong", "broken")


def test_jwt_tokens_are_signed_and_have_distinct_ids() -> None:
    tokens = JwtTokens("test-signing-key-for-jwt-only-123456")
    actor = Principal(uuid4(), "synthetic", UserRole.ADMIN, None, token_version=3)
    first, second = tokens.issue(actor), tokens.issue(actor)
    assert first != second
    assert first.count(".") == 2
    claims = tokens.decode(first)
    assert claims.user_id == actor.id and claims.version == 3
    with pytest.raises(ApplicationError):
        JwtTokens("different-test-signing-key-123456789").decode(first)


@pytest.mark.parametrize(
    "change",
    [
        "expired",
        "audience",
        "issuer",
        "missing",
        "version",
        "algorithm",
        "subject",
        "future",
        "unsigned",
        "malformed",
    ],
)
def test_invalid_jwt_is_rejected(change: str) -> None:
    import jwt
    import time

    secret = "test-signing-key-for-jwt-only-123456"
    tokens = JwtTokens(secret)
    token = tokens.issue(Principal(uuid4(), "synthetic", UserRole.ADMIN, None))
    payload = jwt.decode(
        token, secret, algorithms=["HS256"], audience=tokens.AUDIENCE, issuer=tokens.ISSUER
    )
    algorithm = "HS256"
    if change == "expired":
        payload.update(
            iat=int(time.time()) - 100, nbf=int(time.time()) - 100, exp=int(time.time()) - 1
        )
    elif change == "audience":
        payload["aud"] = "other-service"
    elif change == "issuer":
        payload["iss"] = "other-issuer"
    elif change == "missing":
        del payload["exp"]
    elif change == "version":
        payload["ver"] = True
    elif change == "algorithm":
        algorithm = "HS384"
    elif change == "subject":
        payload["sub"] = "not-a-uuid"
    elif change == "future":
        payload.update(
            iat=int(time.time()) + 3600, nbf=int(time.time()) + 3600, exp=int(time.time()) + 4000
        )
    if change == "unsigned":
        token = jwt.encode(payload, key="", algorithm="none")
    elif change == "malformed":
        token = "invalid-token"
    else:
        token = jwt.encode(payload, secret, algorithm=algorithm)
    with pytest.raises(ApplicationError):
        tokens.decode(token)


async def test_cancelled_hash_retains_its_memory_slot() -> None:
    import asyncio
    import threading

    passwords = ScryptPasswords()
    passwords._slots = asyncio.Semaphore(1)
    started, release, second_started = threading.Event(), threading.Event(), threading.Event()

    def derive(password: str, salt: bytes) -> str:
        if password == "first":
            started.set()
            assert release.wait(timeout=5)
        else:
            second_started.set()
        return "test-hash"

    passwords._derive = derive  # type: ignore[method-assign]
    first = asyncio.create_task(passwords.hash("first"))
    second: asyncio.Task[str] | None = None
    try:
        assert await asyncio.to_thread(started.wait, 2)
        first.cancel()
        second = asyncio.create_task(passwords.hash("second"))
        await asyncio.sleep(0.01)
        assert not second_started.is_set()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        if second:
            await second
    assert second_started.is_set()
