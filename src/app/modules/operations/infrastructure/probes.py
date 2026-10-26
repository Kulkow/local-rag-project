"""External service adapters for the readiness port."""

from dataclasses import dataclass

import httpx
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(frozen=True)
class DatabaseProbe:
    engine: AsyncEngine

    async def check(self) -> bool:
        async with self.engine.connect() as connection:
            return (
                await connection.execute(text("SELECT 1 FROM platform_state WHERE id = 1"))
            ).scalar_one_or_none() == 1


@dataclass(frozen=True)
class HttpProbe:
    client: httpx.AsyncClient
    url: str

    async def check(self) -> bool:
        return (await self.client.get(self.url)).is_success


@dataclass(frozen=True)
class RedisProbe:
    url: str

    async def check(self) -> bool:
        async with Redis.from_url(self.url, socket_connect_timeout=2, socket_timeout=2) as client:
            return bool(await client.ping())
