import asyncio
import hashlib
import secrets
from datetime import UTC, datetime
from uuid import UUID, uuid4

import jwt

from app.modules.identity.application.service import TokenClaims
from app.modules.identity.domain.entities import Principal
from app.modules.shared.domain.errors import ApplicationError


class ScryptPasswords:
    def __init__(self) -> None:
        self._slots = asyncio.Semaphore(2)

    @staticmethod
    def _derive(password: str, salt: bytes) -> str:
        return hashlib.scrypt(
            password.encode(), salt=salt, n=2**17, r=8, p=1, maxmem=256 * 1024 * 1024, dklen=32
        ).hex()

    async def _calculate(self, password: str, salt: bytes) -> str:
        async with self._slots:
            task = asyncio.create_task(asyncio.to_thread(self._derive, password, salt))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                # Keep the slot until the native hash finishes; cancellation cannot stop a thread.
                await task
                raise

    async def hash(self, password: str) -> str:
        salt = secrets.token_bytes(16)
        value = await self._calculate(password, salt)
        return f"scrypt${salt.hex()}${value}"

    async def verify(self, password: str, encoded: str | None) -> bool:
        # Missing users receive the same expensive derivation, avoiding a fast enumeration path.
        parts = (encoded or f"scrypt${'00' * 16}${'00' * 32}").split("$")
        if len(parts) != 3 or parts[0] != "scrypt":
            return False
        try:
            value = await self._calculate(password, bytes.fromhex(parts[1]))
            return secrets.compare_digest(value, parts[2])
        except ValueError:
            return False


class JwtTokens:
    ISSUER = "enterprise-rag"
    AUDIENCE = "web-admin"
    LIFETIME_SECONDS = 28800

    def __init__(self, secret: str) -> None:
        if len(secret.encode()) < 32:
            raise ValueError("JWT signing key must contain at least 32 bytes")
        self._secret = secret

    def issue(self, actor: Principal) -> str:
        now = int(datetime.now(UTC).timestamp())
        return jwt.encode(
            {
                "sub": str(actor.id),
                "ver": actor.token_version,
                "iat": now,
                "nbf": now,
                "exp": now + self.LIFETIME_SECONDS,
                "iss": self.ISSUER,
                "aud": self.AUDIENCE,
                "jti": str(uuid4()),
            },
            self._secret,
            algorithm="HS256",
        )

    def decode(self, token: str) -> TokenClaims:
        try:
            if len(token) > 2048:
                raise ValueError("Token too long")
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                issuer=self.ISSUER,
                audience=self.AUDIENCE,
                options={"require": ["sub", "ver", "iat", "nbf", "exp", "iss", "aud", "jti"]},
            )
            if type(claims["ver"]) is not int or claims["ver"] < 0:
                raise ValueError("Invalid token version")
            if any(type(claims[key]) is not int for key in ("iat", "nbf", "exp")):
                raise ValueError("Invalid timestamps")
            if (
                not 0 < claims["exp"] - claims["iat"] <= self.LIFETIME_SECONDS
                or claims["nbf"] != claims["iat"]
            ):
                raise ValueError("Invalid token lifetime")
            UUID(claims["jti"])
            return TokenClaims(UUID(claims["sub"]), claims["ver"])
        except (jwt.InvalidTokenError, ValueError, TypeError, AttributeError) as exc:
            raise ApplicationError("unauthorized", "Invalid or expired access token") from exc

    def digest(self, value: str) -> str:
        # Used only for the shared login throttle, never for token storage.
        return hashlib.sha256(value.encode()).hexdigest()
