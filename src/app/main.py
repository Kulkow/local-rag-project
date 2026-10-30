from dataclasses import asdict
import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.identity.api.routes import router as identity_router
from app.modules.families.api.routes import router as families_router
from app.modules.identity.infrastructure.security import ScryptPasswords
from app.modules.shared.domain.errors import ApplicationError

from app.modules.documents.api.routes import router as documents_router
from app.modules.rag.api.routes import router as rag_router
from app.modules.rag.api.streaming import router as rag_stream_router
from app.modules.documents.application.extraction import ExtractorRegistry
from app.modules.documents.infrastructure.pdf_extractor import PdfExtractor
from app.modules.documents.infrastructure.object_storage import MinioOriginalStorage
from app.observability.rag_metrics import PrometheusRagObserver
from app.core.settings import Settings
from app.infrastructure.db.connection import create_engine
from app.modules.operations.api.routes import router
from app.modules.operations.application.readiness import InspectReadiness
from app.modules.operations.infrastructure.probes import DatabaseProbe, HttpProbe, RedisProbe

logger = logging.getLogger("app.requests")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        config = settings or Settings()
        app.state.settings = config
        app.state.engine = create_engine(config.database_url.get_secret_value())
        app.state.db_session_factory = async_sessionmaker(app.state.engine, expire_on_commit=False)
        app.state.passwords = ScryptPasswords()
        app.state.upload_slots = asyncio.Semaphore(2)
        app.state.extraction_slots = asyncio.Semaphore(1)
        app.state.rag_slots = asyncio.Semaphore(1)
        app.state.extractors = ExtractorRegistry([PdfExtractor()])
        app.state.original_storage = None
        try:
            app.state.original_storage = await asyncio.to_thread(
                MinioOriginalStorage,
                config.minio_url,
                config.minio_access_key.get_secret_value(),
                config.minio_secret_key.get_secret_value(),
                config.documents_bucket,
            )
            async with httpx.AsyncClient(timeout=3, follow_redirects=False) as client:
                app.state.readiness = InspectReadiness(
                    {
                        "postgresql": DatabaseProbe(app.state.engine),
                        "redis": RedisProbe(config.redis_url),
                        "qdrant": HttpProbe(client, config.qdrant_url + "/readyz"),
                        "minio": HttpProbe(client, config.minio_url + "/minio/health/ready"),
                        "ollama": HttpProbe(client, config.ollama_url + "/api/tags"),
                    }
                )
                yield
        finally:
            try:
                if app.state.original_storage is not None:
                    await app.state.original_storage.close()
            finally:
                await app.state.engine.dispose()

    app = FastAPI(title="Enterprise RAG Platform", version="0.1.0", lifespan=lifespan)
    app.state.rag_metrics = PrometheusRagObserver()

    @app.get("/internal/metrics", include_in_schema=False)
    async def rag_metrics() -> Response:
        return Response(app.state.rag_metrics.render(), media_type="text/plain; version=0.0.4")

    app.include_router(router)
    app.include_router(identity_router)
    app.include_router(families_router)
    app.include_router(documents_router)
    app.include_router(rag_router)
    app.include_router(rag_stream_router)

    @app.exception_handler(ApplicationError)
    async def application_error(request: Request, exc: ApplicationError) -> JSONResponse:
        status = {
            "unauthorized": 401,
            "forbidden": 403,
            "not_found": 404,
            "conflict": 409,
            "invalid": 422,
            "throttled": 429,
            "payload_too_large": 413,
            "unsupported_media": 415,
            "storage_unavailable": 503,
            "upload_timeout": 408,
        }[exc.code]
        headers = {"WWW-Authenticate": "Bearer"} if status == 401 else {}
        if status == 429:
            headers["Retry-After"] = "60"
        content: dict[str, object] = {"detail": str(exc)}
        if hasattr(request.state, "rag_timings"):
            content["timings"] = request.state.rag_timings
            content["llm_usage"] = asdict(request.state.rag_measurements.usage_snapshot())
            content["trace_id"] = request.state.request_id
        return JSONResponse(content, status_code=status, headers=headers)

    @app.exception_handler(IntegrityError)
    async def integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        return JSONResponse(
            {
                "detail": "Conflicting data or linked records. Check username, member link, users, pets and documents."
            },
            status_code=409,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic input/context can contain submitted passwords; return only field locations.
        return JSONResponse(
            {
                "detail": [
                    {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
                    for error in exc.errors()
                ]
            },
            status_code=422,
        )

    @app.middleware("http")
    async def request_metadata(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = str(uuid4())
        request.state.request_id = request_id
        started = perf_counter()
        response = await call_next(request)
        elapsed = (perf_counter() - started) * 1000
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-ID"] = request_id
        response.headers["Server-Timing"] = f"total;dur={elapsed:.2f}"
        logger.info(
            json.dumps(
                {
                    "event": "request",
                    "request_id": request_id,
                    "method": request.method,
                    "status": response.status_code,
                    "duration_ms": round(elapsed, 2),
                }
            )
        )
        return response

    return app


app = create_app()
