import asyncio
import secrets
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text

router = APIRouter()
basic = HTTPBasic()


class Health(BaseModel):
    status: Literal["ok"] = "ok"


class Readiness(BaseModel):
    status: Literal["ready", "degraded"]
    services: dict[str, bool]


def require_admin(request: Request, credentials: Annotated[HTTPBasicCredentials, Depends(basic)]) -> None:
    settings = request.app.state.settings
    username_ok = secrets.compare_digest(credentials.username.encode(), settings.admin_username.encode())
    password_ok = secrets.compare_digest(credentials.password.encode(), settings.admin_password.get_secret_value().encode())
    if not (username_ok and password_ok):
        raise HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Basic"})


@router.get("/health", response_model=Health)
async def health() -> Health:
    return Health()


async def check_database(request: Request) -> bool:
    try:
        async with asyncio.timeout(4):
            async with request.app.state.engine.connect() as connection:
                await connection.execute(text("SELECT 1 FROM platform_state WHERE id = 1"))
        return True
    except Exception:
        return False


async def check_http(client: httpx.AsyncClient, url: str) -> bool:
    try:
        return (await client.get(url)).is_success
    except httpx.HTTPError:
        return False


async def check_redis(url: str) -> bool:
    try:
        async with Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2) as client:
            return bool(await client.ping())
    except Exception:
        return False


async def inspect_services(request: Request) -> dict[str, bool]:
    settings = request.app.state.settings
    async with httpx.AsyncClient(timeout=3, follow_redirects=False) as client:
        results = await asyncio.gather(
            check_database(request), check_redis(settings.redis_url),
            check_http(client, settings.qdrant_url + "/readyz"),
            check_http(client, settings.minio_url + "/minio/health/ready"),
            check_http(client, settings.ollama_url + "/api/tags"),
        )
    return dict(zip(("postgresql", "redis", "qdrant", "minio", "ollama"), results, strict=True))


@router.get("/ready", response_model=Readiness, dependencies=[Depends(require_admin)])
async def ready(request: Request, response: Response) -> Readiness:
    services = await inspect_services(request)
    success = all(services.values())
    response.status_code = 200 if success else 503
    return Readiness(status="ready" if success else "degraded", services=services)
