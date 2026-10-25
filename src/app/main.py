import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request, Response

from app.api.health import router
from app.core.settings import Settings
from app.infrastructure.db.connection import create_engine

logger = logging.getLogger("app.requests")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        config = settings or Settings()
        app.state.settings = config
        app.state.engine = create_engine(config.database_url.get_secret_value())
        yield
        await app.state.engine.dispose()

    app = FastAPI(title="Enterprise RAG Platform", version="0.1.0", lifespan=lifespan)
    app.include_router(router)

    @app.middleware("http")
    async def request_metadata(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = str(uuid4())
        started = perf_counter()
        response = await call_next(request)
        elapsed = (perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["Server-Timing"] = f"total;dur={elapsed:.2f}"
        logger.info(json.dumps({"event": "request", "request_id": request_id,
                                "method": request.method, "status": response.status_code,
                                "duration_ms": round(elapsed, 2)}))
        return response

    return app


app = create_app()
